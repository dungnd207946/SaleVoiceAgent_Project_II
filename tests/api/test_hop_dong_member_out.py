"""Cổng đóng băng tập trường của `MemberOut` — hợp đồng với FE `thanhVien.ts`.

VÌ SAO CẦN CỔNG NÀY. 2026-08-09 FE thêm hai trường vào `MemberOut` của nó
(`lifecycle`, `isOrgOwner`) và ghi trong docstring rằng backend trả kèm. Backend
KHÔNG BAO GIỜ trả. `taiThanhVien()` phía FE là `goi<MemberOut[]>()` trần — không
chuẩn hoá, không giá trị mặc định — nên `undefined` chạy thẳng vào UI:

  · cột «Trạng thái» hiện pill trống (`NHAN_LIFECYCLE[undefined]`)
  · bộ lọc theo trạng thái trả bảng RỖNG (`m.lifecycle === locTrangThai`)
  · mục «Gửi lại lời mời» KHÔNG BAO GIỜ hiện (`m.lifecycle === 'pending'`)

Sống suốt 8 ngày. Không cổng nào bắt được, vì cổng duy nhất có liên quan
(`membership-shape-parity.test.ts` bên FE) so **fake MSW với kiểu FE** — và fake
CÓ đủ hai trường. Fake nói dối theo hướng dễ hơn thật, nên nó che đúng lớp lỗi nó
sinh ra để bắt. Đây là bẫy mà CLAUDE.md repo FE đã cảnh báo bằng cả một mục.

CỔNG NÀY ĐO ĐƯỢC GÌ, VÀ KHÔNG ĐO ĐƯỢC GÌ. Nó không so được hai repo — chúng là
hai repo git rời. Nó chỉ đóng băng tập trường phía backend: thêm/bớt một trường
là bài này đỏ, và người sửa buộc phải sửa danh sách dưới đây, tức buộc phải đọc
dòng "sửa `thanhVien.ts` cùng commit". Một cổng bắt được sự QUÊN, không bắt được
sự CỐ Ý sai — nhưng cái đã xảy ra là quên.
"""

import typing

from portal.modules.auth.contracts import MemberOut

# Tập trường mà FE `features/auth/thanhVien.ts` khai trong `interface MemberOut`.
# ĐỔI DANH SÁCH NÀY = PHẢI sửa `thanhVien.ts` + fake MSW trong CÙNG commit.
TRUONG_FE_MONG_DOI = {
    "kind",
    "userId",
    "name",
    "email",
    "roleId",
    "role",
    "lifecycle",
    "invitedAt",
    "expiresAt",
    "avatar",
}


def test_member_out_dung_tap_truong_fe_khai() -> None:
    assert set(MemberOut.model_fields) == TRUONG_FE_MONG_DOI, (
        "Tập trường `MemberOut` lệch khỏi hợp đồng FE.\n"
        "Thêm trường  -> FE bỏ qua nó (vô hại, nhưng sửa danh sách trên cho khớp).\n"
        "BỚT trường   -> FE nhận `undefined` và KHÔNG có chuẩn hoá nào chặn lại;\n"
        "                triệu chứng là một cột trống hoặc một bộ lọc trả rỗng,\n"
        "                KHÔNG phải một lỗi. Xem docstring đầu file."
    )


def test_ba_truong_nullable_cua_hang_loi_moi() -> None:
    """`kind='invite'` cho email CHƯA có tài khoản không có `users` nào phía sau.

    Ba trường này KHÔNG được là `str` trần: FE dùng `userId` làm React key và làm
    path param của ba đường ghi, nên một `str` ở hợp đồng là lời hứa rằng nó luôn
    có — và FE sẽ dựng `/api/v1/members/undefined`.

    ⚠ Brief gốc canh `"NoneType" in str(annotation)` — sai với Python 3.13/pydantic
    v2 ở đây: `str | None` in stringify thành `"str | None"`, không bao giờ chứa
    chữ "NoneType" dù trường ĐÚNG nullable. `"None" in str(...)` (bản trước của
    bài này) tránh được cái sai đó nhưng vẫn LỎNG — nó khớp bất kỳ chuỗi nào có
    ba ký tự "None" xuất hiện ở BẤT ĐÂU, kể cả trong một literal tên trường hay
    một chú thích, không phải bằng chứng annotation THỰC SỰ là union với
    `NoneType`. Cổng phải hỏi đúng câu hỏi đó bằng `typing.get_args` (đúng lối
    `test_kind_la_hai_gia_tri` ngay dưới đã dùng) thay vì đoán qua stringify.
    """
    for ten in ("userId", "name", "lifecycle", "avatar"):
        assert type(None) in typing.get_args(MemberOut.model_fields[ten].annotation), (
            f"`{ten}` phải nullable — hàng lời mời của email chưa có tài khoản không có nó"
        )


def test_kind_la_hai_gia_tri() -> None:
    """Thêm giá trị thứ ba = FE có một nhánh nó chưa render."""
    assert set(typing.get_args(MemberOut.model_fields["kind"].annotation)) == {"member", "invite"}


def test_khong_con_is_org_owner() -> None:
    """`isOrgOwner` KHÔNG được quay lại — cột nguồn đã bị xoá.

    FE từng khai trường này, phái sinh từ `users.org_role === 'owner'`. Cột
    `org_role` bị xoá ở migration `0106_bo_organizations`, nên backend không còn
    cách nào tính nó. FE đã gỡ 2026-08-17.

    Bài này neo lại chiều đó: ai thêm `isOrgOwner` vào contract là đang hồi sinh
    một khái niệm đã chết cùng tầng organization, và sẽ phải trả lời câu "lấy giá
    trị từ đâu" trước khi bài này xanh.
    """
    assert "isOrgOwner" not in MemberOut.model_fields
