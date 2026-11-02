"""Cổng 5–6 của spec M2b §7 — hai luật cross-field, cưỡng chế trong Pydantic.

KHÔNG cần DB, không cần app: đây là test của HỢP ĐỒNG. Đặt hai luật này ở contract
chứ không ở service là để chúng trả 422 có `error.fields`, và một test đơn vị chạy
trong 2ms là bằng chứng chúng thật sự nằm ở đó.

`roleId` ở `MS_ANPHU` là một chuỗi BỊA — file này không đụng DB, nên "vai trò đó
có thật hay không" không phải điều nó kiểm (đó là việc của
`_kiem_role_thuoc_to_chuc` + `test_tao_user.py::test_cong_4b_...`, có DB thật).
Ở tầng contract, `roleId` chỉ cần là `str`.
"""

import pytest
from pydantic import ValidationError

from portal.modules.auth.contracts import SuaUserIn, TaoUserIn

MS_ANPHU = [{"workspaceId": "cs_anphu", "roleId": "r_bia"}]


def test_user_khong_membership_la_hop_le():
    """ĐẢO NGƯỢC hai luật cũ (2026-08-15).

    Bản trước có hai cổng cross-field:
      · Cổng 5 — `orgRole='owner'` + memberships không rỗng ⇒ 422
      · Cổng 6 — `orgRole='member'` + memberships rỗng ⇒ 422

    Cổng 5 mất cùng `orgRole`. Cổng 6 đứng trên PQ_01 Q01 ("phiên không workspace
    là trạng thái HỎNG"), mà chính Q01 đã bị đảo ngược để mở tự đăng ký — xem
    spec bo-organization §5.0. Giữ nó lại sẽ cấm admin tạo ra đúng thứ mà
    `POST /auth/register` tạo ra hàng ngày: một tài khoản chưa thuộc workspace nào.

    Test này neo chiều NGƯỢC LẠI: form tối thiểu phải ĐƯỢC nhận.
    """
    assert TaoUserIn(email="a@b.vn", name="A").memberships == []
    assert len(TaoUserIn(email="a@b.vn", name="A", memberships=MS_ANPHU).memberships) == 1


def test_orgrole_gui_len_bi_tu_choi():
    """`extra="forbid"` — `orgRole` từng là trường thật.

    Gửi lên phải 422 chứ không im lặng bỏ qua: một FE cũ chưa deploy sẽ tiếp tục
    gửi nó, và im lặng nhận nghĩa là người vận hành tưởng đang set quyền tổ chức
    trong khi không gì xảy ra.
    """
    with pytest.raises(ValidationError):
        TaoUserIn(email="a@b.vn", name="A", orgRole="owner")


def test_workspace_trung_trong_cung_form_bi_tu_choi():
    """PK (user_id, tenant_id) sẽ chặn ở INSERT — bằng UniqueViolation -> 500.

    Cùng sự thật, ở đây thành 422 có tên field.
    """
    with pytest.raises(ValidationError, match="một lần"):
        TaoUserIn(
            email="a@b.vn",
            name="A",
            memberships=[
                {"workspaceId": "cs_anphu", "roleId": "r_bia_1"},
                {"workspaceId": "cs_anphu", "roleId": "r_bia_2"},
            ],
        )


@pytest.mark.parametrize("email", ["khong-co-a-thuong", "thieu@tenmien", "co dau cach@a.vn", "@a.vn"])
def test_email_sai_dang_bi_tu_choi(email: str):
    with pytest.raises(ValidationError):
        TaoUserIn(email=email, name="A", memberships=MS_ANPHU)


def test_email_duoc_chuan_hoa_ngay_o_contract():
    """Chuẩn hoá ở BIÊN NHẬP — CHECK `email = lower(email)` ở DB là lưới thứ hai."""
    assert TaoUserIn(email="  Mai.Anh@AnPhu.VN ", name="A", memberships=MS_ANPHU).email == "mai.anh@anphu.vn"


@pytest.mark.parametrize("ten", ["", "   ", "\t\n"])
def test_ten_rong_hoac_chi_co_dau_cach_bi_tu_choi(ten: str):
    """`min_length=1` một mình KHÔNG bắt được `'   '` — nó dài 3 ký tự."""
    with pytest.raises(ValidationError):
        TaoUserIn(email="a@b.vn", name=ten, memberships=MS_ANPHU)


def test_phone_va_job_title_rong_thanh_none():
    """Form HTML luôn gửi `''` cho ô trống. Cột nullable không có DEFAULT '' (0103)."""
    v = TaoUserIn(email="a@b.vn", name="A", phone="  ", jobTitle="", memberships=MS_ANPHU)
    assert v.phone is None
    assert v.jobTitle is None


# `test_role_membership_ngoai_bon_gia_tri_bi_tu_choi` (canh CHECK 4-giá-trị của
# migration 0101) bị XOÁ ở round sửa "roleId" — đúng điểm của quyết định
# 2026-08-04: `roleId` là id của `control.roles`, KHÔNG còn một enum 4 giá trị ở
# tầng Pydantic để canh. "roleId lạ" giờ là một câu hỏi CHỈ DB trả lời được (org
# nào sở hữu id đó) — xem `_kiem_role_thuoc_to_chuc` + `test_cong_4b_...` ở
# `test_tao_user.py`. `org_role` và vai trò-trong-workspace vẫn là hai từ vựng
# khác nhau (`owner` chỉ tồn tại ở `org_role`) — điều đó không đổi, chỉ là nó
# không còn kiểm được bằng `pytest.raises(ValidationError)` ở tầng contract.


@pytest.mark.parametrize("lc", ["pending", "deleted", ""])
def test_sua_khong_dat_duoc_lifecycle_pending(lc: str):
    """`pending` không nằm trong `LifecycleSuaDuoc` — vào/ra `pending` là việc của thư mời.

    Cho form đặt `pending` nghĩa là cho phép biến một user đang hoạt động thành
    user không mật khẩu, và CHECK song điều kiện của 0103 sẽ nổ thành 500.
    """
    with pytest.raises(ValidationError):
        SuaUserIn(name="A", lifecycle=lc, memberships=MS_ANPHU)


def test_sua_lifecycle_none_la_hop_le_nghia_la_giu_nguyen():
    assert SuaUserIn(name="A", memberships=MS_ANPHU).lifecycle is None


def test_sua_khong_nhan_truong_email():
    """`SuaUserIn` KHÔNG có `email` — email là khoá đăng nhập, không sửa qua form.

    Trước 2026-08-15 model này `extra` mặc định (ignore), nên gửi `email` lên chỉ
    bị bỏ qua âm thầm. `extra="forbid"` thêm cùng lúc xoá `orgRole` biến nó thành
    422 — nói thẳng thay vì để người vận hành tưởng mình vừa đổi email của ai đó.
    """
    with pytest.raises(ValidationError):
        SuaUserIn(name="A", email="moi@b.vn")


def test_mat_khau_rong_bi_tu_choi():
    """Sàn 10 ký tự ĐÃ BỎ 2026-08-22 theo yêu cầu người dùng — xem docstring
    `NhanLoiMoiIn`. Chỉ còn chuỗi rỗng bị chặn: `min_length=1` là phép kiểm "có
    gõ gì không", không phải một chính sách độ mạnh.
    """
    from portal.modules.auth.contracts import NhanLoiMoiIn

    with pytest.raises(ValidationError):
        NhanLoiMoiIn(token="x", password="")


@pytest.mark.parametrize("mk", ["a", "ngan", "chin_kytu"])
def test_mat_khau_ngan_duoc_nhan(mk: str):
    """Canh đúng cái vừa bỏ: mật khẩu ngắn hơn 10 ký tự KHÔNG còn bị 422.

    Test này đỏ nếu ai đó khôi phục `min_length=10` mà không đọc quyết định
    2026-08-22.
    """
    from portal.modules.auth.contracts import NhanLoiMoiIn

    assert NhanLoiMoiIn(token="x", password=mk).password == mk


def test_mat_khau_dai_hon_200_van_bi_tu_choi():
    """`max_length` KHÔNG cùng loại với `min_length` vừa bỏ: nó là lá chắn DoS
    cho Argon2, không phải chính sách độ mạnh. Quyết định 2026-08-22 giữ nó.
    """
    from portal.modules.auth.contracts import NhanLoiMoiIn

    with pytest.raises(ValidationError):
        NhanLoiMoiIn(token="x", password="a" * 201)
