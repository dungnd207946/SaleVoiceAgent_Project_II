"""MẶT TIỀN của module auth — file DUY NHẤT module khác được import.

Import `service.py` / `repo.py` / `router.py` từ module khác là LỖI CI
(tests/test_module_boundaries.py đọc AST, không phải quy ước trong đầu ai).

Tên trường theo camelCase vì đây là hợp đồng HTTP — FE đã có kiểu `Session`
tương ứng ở `src/lib/session.tsx` của repo frontend và spec §4.2 buộc hai bên khớp.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

# `OrgRole = Literal["owner", "member"]` ĐÃ XOÁ 2026-08-15 cùng `users.org_role`.
# Chỉ còn MỘT trục quyền: vai trò trong một workspace (`control.roles`, qua
# `control.memberships`). Không có membership là không có quyền, không ngoại lệ.

LifecycleSuaDuoc = Literal["active", "suspended"]
"""`pending` KHÔNG có ở đây: chuyển vào/ra `pending` là việc của thư mời, không
phải của form sửa. CHECK song điều kiện ở migration 0103 chặn mọi cách khác."""

# Cố tình lỏng — đây không phải chỗ quyết định email nào giao được thư. Nó bắt
# đúng ba lỗi gõ hay gặp (thiếu @, thiếu tên miền, có dấu cách) và không hơn.
# `email-validator` chưa nằm trong dependency, và thêm một gói để chặt hơn ở một
# form nội bộ là cái giá không ai đòi.
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _rong_thanh_none(v: str | None) -> str | None:
    """`''` và `None` cùng nghĩa "không có". Gộp ở BIÊN NHẬP về một cách viết.

    Cột `phone`/`job_title` nullable và không có DEFAULT '' (migration 0103) —
    để mọi truy vấn sau chỉ phải kiểm một thứ. Form HTML thì luôn gửi `''` cho ô
    trống, nên chỗ gộp phải ở đây.
    """
    if v is None:
        return None
    v = v.strip()
    return v or None


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    initials: str
    """Hai chữ trên avatar vuông ở chân sidebar. SUY từ `name`, không phải cột DB.

    Một cột `initials` trong bảng users là bản sao thứ hai của thông tin đã có
    trong `name` — hai bản sao thì có ngày lệch, và không có nguồn nào đúng.
    """
    avatar: str
    """Data URI SVG DiceBear (style ở `core/avatar.py`), seed = `avatar_seed`
    user tự chọn (màn Hồ sơ, migration 0952) hoặc `name` khi chưa chọn — SUY
    lúc dựng payload, không lưu SVG.

    GIỮ `initials` bên cạnh: FE cần fallback chữ khi ảnh chưa nạp/aria, và bỏ
    field đang có là phá hợp đồng với FE cũ. Nguồn duy nhất: `core/avatar.py`.
    """
    coMatKhau: bool
    """`password_hash IS NOT NULL` — FE dùng để thay khối «Đổi mật khẩu» bằng
    câu «Tài khoản Google» thay vì để người dùng gõ rồi mới ăn 409."""
    phone: str | None
    jobTitle: str | None
    """Hai cột 0103 — màn «Hồ sơ & tuỳ chọn» đọc từ CHÍNH session, không mở
    thêm một GET riêng cho hai chuỗi đã nằm sẵn trong bảng users."""


class SuaHoSoIn(BaseModel):
    """`PATCH /me/ho-so` — VẮNG KHOÁ = không đổi (đọc `model_fields_set`).

    `avatarSeed: null` TƯỜNG MINH là một lệnh: về avatar mặc định suy từ tên.
    `name: null` thì KHÔNG có nghĩa nào — service từ chối thay vì im lặng bỏ
    qua một payload dị dạng.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    jobTitle: str | None = Field(default=None, max_length=120)
    avatarSeed: str | None = Field(default=None, max_length=64)

    _gon = field_validator("phone", "jobTitle", "avatarSeed", mode="before")(_rong_thanh_none)

    @field_validator("name")
    @classmethod
    def _ten_khong_chi_co_dau_cach(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Tên không được để trống")
        return v


class GoiYAvatarOut(BaseModel):
    """Một ô của lưới gợi ý — chọn xong FE gửi đúng `seed` này vào `avatarSeed`."""

    seed: str
    avatar: str


class DoiMatKhauIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matKhauHienTai: str
    """Không ràng độ dài: luật 10–200 là của mật khẩu MỚI; mật khẩu cũ có thể
    được đặt trước khi luật ra đời — chặn ở đây là khoá người dùng cũ khỏi chính
    việc nâng cấp mật khẩu của họ."""
    matKhauMoi: str = Field(min_length=10, max_length=200)


class WorkspaceOut(BaseModel):
    id: str
    slug: str
    """DƯ CÓ CHỦ Ý, cùng giá trị với `id`.

    control.tenants.id CHÍNH LÀ slug — nó đi vào tên role agent_<id> và vào đường
    dẫn tenants/<id>/ trên kho tệp. Giữ hai trường để FE không phải sửa, và để
    lúc nào có người thật sự cần hai khái niệm khác nhau (đổi tên hiển thị mà giữ
    khoá cách ly) thì trường đã có chỗ. Xem spec §4.3②.
    """
    name: str
    plan: str | None
    """LUÔN None ở MVP.

    control.tenants CỐ Ý không có cột plan: "hoá đơn không được gắn vào khoá cách
    ly" (migration 0002). Màn billing đã hoãn khỏi MVP. Đường lùi đã để sẵn là
    bảng `accounts` PHÍA TRÊN tenants. Xem spec §4.3①.
    """


# `OrganizationOut` ĐÃ XOÁ 2026-08-15 cùng bảng `control.organizations`.


class MemberOut(BaseModel):
    """MỘT HÀNG của bảng thành viên — và từ 2026-08-22 nó là MỘT TRONG HAI LOẠI hàng.

    Trước đó mọi hàng đều là một `memberships`. Nay `GET /members` trả thêm hàng
    LỜI MỜI ĐANG TREO, vì một email chưa có tài khoản không còn hàng `users` nào để
    xuất hiện — mà nó vẫn phải xuất hiện ở đâu đó, nếu không thì mời 10 người xong
    bảng không đổi gì và không có chỗ nào bấm "gửi lại".
    """

    kind: Literal["member", "invite"]
    """`invite` = lời mời đang treo, CHƯA ai nhận. Đọc trường này TRƯỚC mọi trường
    khác: nó quyết định ba trường dưới có giá trị hay không, và quyết định hàng đó
    dùng đường ghi nào (`/members/{userId}` hay `/members/invites/{email}`)."""

    userId: str | None
    """`None` ⇔ `kind='invite'` cho một email chưa có tài khoản.

    ĐÂY LÀ TRƯỜNG DỄ GÂY LỖI NHẤT của hợp đồng này. Nó là React key và là path
    param của `PATCH`/`DELETE /members/{id}` — một `None` chạy lọt sẽ dựng
    `/api/v1/members/undefined` và trả 404 mà không ai hiểu vì sao. Rẽ theo `kind`.
    """

    name: str | None
    """`None` cùng lúc với `userId` — chưa có hàng `users` nào mang một cái tên.
    Ô định danh của hàng đó hiện `email` thay chỗ."""

    email: str
    """Trường DUY NHẤT luôn có ở cả hai loại hàng — nên nó là định danh của hàng
    lời mời, và là path param của hai đường ghi dành cho chúng."""

    roleId: str
    """ID của `control.roles` — handle ỔN ĐỊNH, thứ FE neo ô chọn vai trò vào.

    Cùng lý lẽ với `MembershipOut.roleId`, chỉ khác màn: bảng thành viên của một
    workspace cũng cho đổi vai trò, nên nó cũng cần id. Trả một mình `role` ở đây
    thì đường leo thang quyền qua bảng thành viên vẫn mở nguyên dù `MembershipOut`
    đã vá.

    Với hàng `invite` đây là vai trò ĐÃ HỨA (`invites.role_id`), sẽ thành
    membership lúc lời mời được nhận.
    """
    role: str
    """TÊN vai trò (migration 0104) — đã là tiếng Việt sẵn ('Người xem'), không
    còn mã 1-trong-4 cần FE dịch (PQ_01 §2.4, chết ở 0104).
    """

    lifecycle: str | None
    """`users.lifecycle` — `active` · `pending` · `suspended`. `None` cùng lúc với
    `userId`.

    THÊM 2026-08-17 để vá một lệch hợp đồng ĐANG CHẠY: FE khai trường này bắt buộc
    trong `MemberOut` của nó (`features/auth/thanhVien.ts`) từ 2026-08-09, nhưng
    backend chưa bao giờ trả. `taiThanhVien()` là `goi<MemberOut[]>()` trần, không
    chuẩn hoá, nên `undefined` chạy thẳng vào UI: cột «Trạng thái» hiện pill trống,
    bộ lọc theo trạng thái trả bảng rỗng, và mục «Gửi lại lời mời» (điều kiện
    `lifecycle === 'pending'`) KHÔNG BAO GIỜ hiện — tức không mời lại được ai.

    Fake MSW của FE thì CÓ trường này, nên cổng `membership-shape-parity` (so fake
    với kiểu FE) xanh suốt thời gian tính năng hỏng. Đúng cái bẫy CLAUDE.md repo FE
    đã cảnh báo: fake là bản sao viết tay, không cổng nào so nó với backend thật.

    `str` chứ KHÔNG `Literal`: cột nguồn là `text` + CHECK ở 0100/0103, và hẹp kiểu
    ở đây là hẹn một 500 vào ngày thêm một trạng thái thứ tư. Cùng lý lẽ
    `UserDetailOut.lifecycle` ngay dưới đã chọn.

    ⚠ KHÔNG PHẢI trạng thái hiển thị của hàng. Hàng `kind='invite'` hiện «Chờ xác
    nhận lời mời» BẤT KỂ `lifecycle` — trạng thái đó suy từ `kind`, không từ đây.
    Trộn hai thứ vào một cột là lý do nhãn `pending` phải đổi tên ở FE (từ «Chờ
    nhận lời mời» thành «Chưa đặt mật khẩu»).
    """

    invitedAt: str | None
    """ISO 8601. Chỉ hàng `invite` (`invites.created_at`)."""

    expiresAt: str | None
    """ISO 8601. Chỉ hàng `invite`. Cho admin biết còn bao lâu trước khi phải mời lại."""

    avatar: str | None
    """Data URI SVG DiceBear — CÙNG CÔNG THỨC với `/me` (`avatar_data_uri(
    avatar_seed or name)`), nên bảng «Thành viên» hiện đúng avatar người đó đã
    set ở «Hồ sơ & tuỳ chọn», không phải một bộ chữ cái FE tự vẽ (2026-08-25 —
    người dùng bắt được hai ảnh lệch nhau giữa bảng và chân sidebar).

    `None` cho hàng `kind='invite'`: FE hiện phong bì cho hàng đó, một data URI
    ở đây là bytes không ai đọc trên mọi lượt tải bảng.
    """


class MoiThanhVienIn(BaseModel):
    """Mời NHIỀU email cùng MỘT vai trò, vào workspace ĐANG MỞ.

    KHÔNG có `workspaceId`: nó suy từ `Principal.tenant_id`. Nhận từ thân request
    là cho một Quản trị của workspace A đẩy người vào workspace B.
    """

    model_config = ConfigDict(extra="forbid")

    emails: list[str] = Field(min_length=1, max_length=50)
    roleId: str = Field(min_length=1)

    @field_validator("emails")
    @classmethod
    def _chuan_hoa(cls, v: list[str]) -> list[str]:
        """Chuẩn hoá + bỏ trùng GIỮ THỨ TỰ. Dán 40 dòng từ Excel thì trùng lặp là
        chuyện thường, và để nó xuống tới `ON CONFLICT` là hai dòng kết quả cho
        cùng một người."""
        thay: list[str] = []
        for x in v:
            e = x.strip().lower()
            if not e:
                continue
            if not _RE_EMAIL.match(e):
                raise ValueError(f"email không đúng dạng: {x}")
            if e not in thay:
                thay.append(e)
        if not thay:
            raise ValueError("cần ít nhất một email")
        return thay


class KetQuaMoiOut(BaseModel):
    """Một email mời THÀNH CÔNG."""

    email: str
    userId: str | None
    """`None` = email chưa có tài khoản. Trước 2026-08-22 luôn có giá trị vì lời
    mời tạo user ngay; nay tài khoản chỉ ra đời lúc người nhận bấm nút."""
    invitePath: str | None
    """`None` = backend đã gửi thư hộ. Có giá trị = mailer tắt/lỗi, admin copy tay.

    Hợp đồng này FE đã chừa sẵn từ 2026-08-09 (`thanhVien.ts`): backend đổi GIÁ TRỊ
    chứ không đổi HÌNH DẠNG.
    """
    daCo: bool
    """`True` = email này ĐÃ CÓ tài khoản `active` trong hệ thống.

    ⚠ ĐỔI NGHĨA 2026-08-22, GIỮ NGUYÊN HÌNH DẠNG — loại thay đổi không cổng nào bắt
    được. Nghĩa CŨ: "đã thêm thẳng vào workspace, KHÔNG phát token, `invitePath`
    luôn `None`". Nghĩa MỚI: chỉ là một sự thật về email đó. Không còn nhánh nào
    thêm thẳng — cả hai nhánh đều phát token và đều gửi thư, nên `invitePath` có
    giá trị ở CẢ HAI khi mailer tắt.

    FE dùng nó để chọn CÂU trong panel kết quả ("đã gửi thư xác nhận tham gia" vs
    "gửi link này cho họ"), không còn để chọn có hiện link hay không.
    """


class LoiMoiTungDongOut(BaseModel):
    """Một email KHÔNG mời được. Lỗi theo TỪNG DÒNG, không phải cho cả lô:
    mời 40 người mà một người hỏng thì 39 người kia phải vào được."""

    email: str
    ma: str


class MoiThanhVienRaOut(BaseModel):
    invites: list[KetQuaMoiOut]
    loi: list[LoiMoiTungDongOut]


class DoiVaiTroThanhVienIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roleId: str = Field(min_length=1)


class SessionOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]
    """Rỗng = user chưa thuộc workspace nào (vừa tự đăng ký). HỢP LỆ, không phải lỗi."""
    currentWorkspaceId: str | None
    """None khi `workspaces` rỗng.

    FE dùng ĐÚNG điều kiện này để đưa tới màn "Tạo workspace đầu tiên" thay vì một
    dashboard rỗng. Trước 2026-08-15 trường này luôn có giá trị vì `/auth/login`
    trả 409 NO_WORKSPACE cho user 0 workspace — xem spec bo-organization §5.0 về
    lý do đảo ngược.
    """
    actions: list[str]
    """Quyền của user TRONG workspace hiện tại. Rỗng khi chưa có workspace.

    Phải khớp CHÍNH XÁC cái `require()` thực thi ở request kế tiếp — nếu không FE
    sẽ ẩn một mục mà API cho, hoặc hiện một mục mà API chặn.
    """


# ═══════════════════════════════════════════════════════════════════════════════
#  M2b — tạo · sửa user (spec docs/superpowers/specs/2026-08-03-m2b-tao-sua-user-design.md)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Không model VÀO nào có `orgId` — tầng tổ chức đã bỏ 2026-08-15 nên khái niệm đó
# không còn tồn tại ở bất kỳ đâu.


class MembershipIn(BaseModel):
    """Một DÒNG trong bảng workspace được truy cập của form.

    Vai trò nằm ở đây, không ở cấp user: một người có thể là Biên tập ở
    workspace này và Người xem ở workspace kia (migration 0101 — PK là
    (user_id, tenant_id)).
    """

    workspaceId: str
    role_id: str = Field(alias="roleId")
    """ID của `control.roles` — KHÔNG phải tên. Quyết định 2026-08-04 (spec §4.0):
    tên vai trò sửa được (đó là điểm của migration 0104), nên một membership neo
    vào TÊN sẽ trỏ vào hư không ngay khi ai đó đổi tên, hoặc — tệ hơn — âm thầm
    trỏ sang một vai trò MỚI trùng tên cũ. `id` là handle ổn định duy nhất.

    Validate `role_id` CÓ TỒN TẠI — `repo.loc_role_khong_ton_tai` — TRƯỚC INSERT,
    cùng lý lẽ đã áp cho `workspaceId` (`repo.loc_workspace_khong_ton_tai`): FK
    cũng chặn, nhưng bằng `ForeignKeyViolationError` -> 500 thay vì 422 có tên
    field. Từ 2026-08-15 vai trò TOÀN CỤC nên "tồn tại" là toàn bộ phép kiểm; mã
    lỗi đổi `ROLE_NOT_IN_ORG` -> `ROLE_NOT_FOUND`.
    """
    expiresAt: datetime | None = None
    """NULL = thành viên thường, không hạn. Có giá trị = vé hỗ trợ tự hết hiệu lực
    (BR-Q08) — không ai phải nhớ thu hồi. `owner` KHÔNG có đường này: quyền trên
    tổ chức không có hạn, nên vé có thời hạn buộc đi qua membership."""


class MembershipOut(BaseModel):
    workspaceId: str
    workspaceName: str
    """Tên để hiện, kèm luôn trong cùng payload. FE không phải đối chiếu id với
    `session.workspaces` — danh sách đó là workspace của ADMIN đang xem, không
    phải của user đang được sửa, và hai tập đó chỉ tình cờ trùng nhau."""
    roleId: str
    """ID của `control.roles` — CÙNG handle mà `MembershipIn.roleId` nhận vào.

    Đường GHI đã neo vào id từ 2026-08-04 vì tên vai trò sửa được, `id` là handle
    ổn định duy nhất (xem docstring `MembershipIn.role_id`). Đường ĐỌC thì mãi tới
    2026-08-07 mới được xem lại — TRƯỚC đó nó chỉ trả `role`, nên FE PHẢI dò ngược
    TÊN -> id qua `/api/v1/roles` để chọn sẵn ô vai trò. Phép dò đó khớp SAI ngay
    khi tên trùng hoặc tên đổi, và <select> im lặng hiện một vai trò khác thứ đã
    cấp. Đoạn này là LÝ DO trường `roleId` ra đời, không phải mô tả hiện trạng:
    phép dò ngược ấy nay đã bị xoá khỏi frontend.

    `workspaceName` ngay phía trên đã áp đúng nguyên tắc này rồi: gửi kèm cái FE
    cần để khỏi tra chéo. Đây là cùng nguyên tắc, ngược chiều — ở đó thiếu TÊN nên
    gửi thêm tên; ở đây thiếu ID nên gửi thêm id. Giữ cả hai: id để neo, tên để hiện.
    """
    role: str
    """TÊN vai trò (migration 0104) — KHÔNG còn là 1-trong-4 `VaiTro`: mỗi tổ
    chức tự định nghĩa vai trò của mình, nên đây là chuỗi bất kỳ đọc từ
    `control.roles.name`, không phải `Literal`."""
    expiresAt: datetime | None


class UserListItemOut(BaseModel):
    """Một hàng trong bảng danh sách. KHÔNG mang `memberships`.

    Danh sách n user × m workspace là n×m hàng cho một màn chỉ hiện một con số.
    Chi tiết đọc qua `GET /users/{id}` lúc mở form.
    """

    id: str
    email: str
    name: str
    jobTitle: str | None
    lifecycle: str
    workspaceCount: int
    """Số DÒNG `memberships` còn hiệu lực — từ 2026-08-15 con số này ĐÚNG BẰNG số
    workspace user thấy được.

    Trước đó hai con số khác nhau ở `owner` (thấy mọi workspace của tổ chức mà
    không cần dòng nào), nên FE phải quyết định theo `orgRole` chứ không theo con
    số này. Nhánh owner đã bỏ cùng tầng tổ chức: `repo.liet_ke_workspace` giờ chỉ
    còn một đường, và con số này là toàn bộ sự thật.
    """


class UserDetailOut(BaseModel):
    id: str
    email: str
    name: str
    phone: str | None
    jobTitle: str | None
    lifecycle: str
    createdAt: datetime
    memberships: list[MembershipOut]


class TruongUserChung(BaseModel):
    """Phần thân dùng chung của tạo và sửa — kể cả HAI LUẬT CROSS-FIELD.

    Luật cross-field ở đây chứ không ở service để chúng trả 422 có `error.fields`
    (xem api/loi.py `_than_loi_validate`): FE tô đỏ đúng ô, không phải đọc một câu
    tiếng Việt rồi đoán ô nào sai.

    `extra="forbid"` thêm 2026-08-15 cùng việc xoá `orgRole`: một FE chưa deploy
    lại sẽ tiếp tục gửi trường đó, và im lặng nhận nghĩa là người vận hành tưởng
    mình đang set quyền tổ chức trong khi không gì xảy ra. 422 nói thẳng.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    jobTitle: str | None = Field(default=None, max_length=120)
    memberships: list[MembershipIn] = Field(default_factory=list)

    _gon = field_validator("phone", "jobTitle", mode="before")(_rong_thanh_none)

    @field_validator("name")
    @classmethod
    def _ten_khong_chi_co_dau_cach(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("tên không được rỗng")
        return v

    @model_validator(mode="after")
    def _kiem_hai_luat(self) -> "TruongUserChung":
        # LUẬT "PHẢI CÓ ÍT NHẤT MỘT WORKSPACE" ĐÃ BỎ (2026-08-15). Nó đứng trên
        # PQ_01 Q01 — "phiên không có workspace nào là trạng thái HỎNG" — mà chính
        # Q01 đã bị đảo ngược để mở tự đăng ký: một user 0 workspace giờ là bình
        # thường (họ vừa đăng ký, chưa tạo workspace nào). Giữ luật này lại sẽ cấm
        # admin tạo ra đúng thứ mà `POST /auth/register` tạo ra hàng ngày.
        #
        # Luật "owner không được cấp membership" cũng bỏ theo: không còn `orgRole`.
        trung = {m.workspaceId for m in self.memberships}
        if len(trung) != len(self.memberships):
            # PK (user_id, tenant_id) sẽ chặn ở INSERT, nhưng bằng một
            # UniqueViolationError -> 500. Cùng sự thật, ở đây thành 422 có tên field.
            raise ValueError("một workspace chỉ được xuất hiện một lần")
        return self


class TaoUserIn(TruongUserChung):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _email_hop_le(cls, v: str) -> str:
        """Chuẩn hoá NGAY Ở ĐÂY, không để service làm.

        Cột có CHECK `email = lower(email)` (0100) là lưới thứ hai, không phải
        lưới thứ nhất. Và `_RE_EMAIL` kiểm sau khi đã lower nên nó không phải lo
        về chữ hoa. Cùng phép chuẩn hoá với `service.chuan_hoa_email`.
        """
        v = v.strip().lower()
        if not _RE_EMAIL.match(v):
            raise ValueError("email không đúng dạng")
        return v


class SuaUserIn(TruongUserChung):
    """KHÔNG sửa được `email` (khoá đăng nhập) và `id` — spec §4.4."""

    lifecycle: LifecycleSuaDuoc | None = None
    """None = giữ nguyên. Đổi lifecycle của user `pending` bị từ chối bằng
    409 USER_PENDING, vì CHECK song điều kiện ở 0103 không cho một user không
    mật khẩu ở trạng thái nào khác `pending`."""


class TaoUserRaOut(BaseModel):
    user: UserDetailOut
    invitePath: str
    """TƯƠNG ĐỐI (`/invite/<token>`), không phải URL tuyệt đối — quyết định §1⑤.

    URL tuyệt đối buộc BE biết origin của FE: một biến môi trường nữa, và nó sai
    ở đúng lúc tệ nhất (mở portal qua IP LAN, qua proxy, qua domain staging). FE
    ghép `location.origin` — nó biết chắc mình đang ở đâu.

    ⚠ Đây là LẦN DUY NHẤT token thô ra khỏi server. DB chỉ có sha256 của nó
    (migration 0103), nên không đường nào đọc lại được. Mất thì Mời lại.
    """


class MoiLaiRaOut(BaseModel):
    invitePath: str | None
    """Token cũ CHẾT khi đường này trả về — `invites.user_id` UNIQUE + ON CONFLICT
    DO UPDATE, nên không bao giờ có hai token sống cho một người.

    `None` = backend đã gửi thư hộ qua mailer (seam `/members/{id}/invite`), cùng
    hợp đồng với `KetQuaMoiOut.invitePath`. Có giá trị = mailer tắt/lỗi, admin copy
    tay. Đường `/users/{id}/invite` (khối đang tắt `USERS_ADMIN_ENABLED`) luôn
    trả một chuỗi — `str` là tập con hợp lệ của `str | None`.
    """


class LoiMoiOut(BaseModel):
    """Màn nhận lời mời hiện được TRƯỚC khi có phiên. Đủ để trả lời "tham gia cái
    gì, với tài khoản nào" — và không hơn.
    """

    email: str
    name: str | None
    """`None` cho `invite_new`: chưa có hàng `users` nào. Màn đó bỏ lời chào theo tên."""

    kind: Literal["signup", "invite_new", "invite_existing"]
    """Suy từ (`tenant_id IS NULL`, `user_id IS NULL`) — hai cột, ba tổ hợp hợp lệ.

    HAI → BA GIÁ TRỊ (2026-08-22). `invite` cũ tách đôi vì hai luồng nay khác nhau
    ở thứ màn hình phải hỏi: `invite_new` cần một mật khẩu, `invite_existing` chỉ
    cần một cú bấm — và gửi `password` ở ca sau là 422, không phải một trường thừa
    vô hại.
    """

    workspaceName: str | None
    """`None` CHỈ khi `kind='signup'`.

    ĐẢO LẠI quyết định 2026-08-15 ("không kèm tên workspace"). Lý lẽ cũ — "lời mời
    mở TRƯỚC khi có phiên, một cái tên lạ là thêm một câu hỏi" — viết khi màn này
    chỉ nói "đặt mật khẩu đi". Nay nó hỏi "có tham gia hay không", và một câu hỏi
    không nói tham gia CÁI GÌ là câu hỏi không trả lời được.

    RÒ RỈ ĐÃ CÂN NHẮC: ai giữ link đọc được tên workspace. Chấp nhận — đó chính là
    thông tin phải nói cho người được hỏi.
    """


class NhanLoiMoiIn(BaseModel):
    token: str = Field(min_length=1)
    password: str | None = Field(default=None, min_length=1, max_length=200)
    """BẮT BUỘC cho `signup`/`invite_new`, PHẢI VẮNG cho `invite_existing` — cưỡng
    chế ở `quan_tri_user.nhan_loi_moi` (422 `INVITE_PASSWORD_REQUIRED` /
    `INVITE_PASSWORD_NOT_ALLOWED`), không ở đây: Pydantic không thấy được token.

    Sàn 10 ký tự ĐÃ BỎ 2026-08-22 (CLAUDE.md Change Log cùng ngày: "mật khẩu tuỳ
    ý, không áp chính sách độ mạnh nào") — nhưng `min_length` KHÔNG bỏ theo, nó
    HẠ xuống `1`: "`min_length=1` KHÔNG phải một cái sàn thu nhỏ — nó chỉ chặn
    chuỗi rỗng" (nguyên văn changelog). `test_mat_khau_ngan_duoc_nhan` canh đúng
    điều đó — "a" (1 ký tự) PHẢI qua; nó không canh việc bỏ hẳn `min_length`.
    `max_length` GIỮ và KHÔNG cùng loại: nó chặn một thân request khổng lồ đi vào
    Argon2, nơi mỗi lần băm cố tình tốn CPU — bỏ nó là mở một đường DoS.
    """


class VaoDangKy(BaseModel):
    """Tự đăng ký — đường công khai, không cần phiên.

    KHÔNG có `password`: mật khẩu đặt ở `POST /invites/accept` sau khi bấm link
    trong thư (ràng buộc độ dài: xem `NhanLoiMoiIn`). Đó là phép xác thực email,
    và nó miễn phí vì luồng lời mời đã có sẵn.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def _email_hop_le(cls, v: str) -> str:
        """Cùng phép chuẩn hoá với `TaoUserIn._email_hop_le` và
        `service.chuan_hoa_email` — CHECK `email = lower(email)` (0100) là lưới
        thứ hai, không phải lưới thứ nhất."""
        v = v.strip().lower()
        if not _RE_EMAIL.match(v):
            raise ValueError("email không đúng dạng")
        return v

    @field_validator("name")
    @classmethod
    def _ten_khong_chi_co_dau_cach(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("tên không được rỗng")
        return v


class DangKyRaOut(BaseModel):
    daGuiLai: bool
    """`True` = tài khoản đã tồn tại ở trạng thái `pending` và thư vừa được GỬI LẠI.

    Tách khỏi nhánh 409: người mất thư có tài khoản `pending`, không có mật khẩu
    để đăng nhập, và đợt này chưa có "quên mật khẩu" — gộp họ vào 409 là nhốt họ
    trong ngõ cụt.
    """


# ═══════════════════════════════════════════════════════════════════════════════
#  M2b — vai trò (spec §4, quyết định 2026-08-04) — migration 0104
# ═══════════════════════════════════════════════════════════════════════════════


class ActionOut(BaseModel):
    """Một trong 13 ô checkbox. Nhãn song ngữ vì FE đã song ngữ (NavLeaf.label)."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    group_name: str = Field(serialization_alias="groupName")
    label_vi: str = Field(serialization_alias="labelVi")
    label_en: str = Field(serialization_alias="labelEn")
    sort_order: int = Field(serialization_alias="sortOrder")


class VaiTroOut(BaseModel):
    """Một dòng ở màn danh sách.

    `userCount` KHÔNG phải trang trí: không có nó thì nút Xoá là một cái bẫy —
    người dùng bấm, nhận 409, và không biết phải làm gì tiếp.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str | None
    user_count: int = Field(serialization_alias="userCount")


class VaiTroChiTietOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str | None
    actions: list[str]


def _lam_sach_ten(v: str) -> str:
    ten = v.strip()
    if not ten:
        raise ValueError("Tên vai trò không được rỗng")
    return ten


def _bo_trung(v: list[str]) -> list[str]:
    """Giữ thứ tự, bỏ trùng. Gửi trùng không phải lỗi người dùng — nhưng
    PK (role_id, action_code) sẽ nổ ở tầng dưới, và một 500 cho một việc vô hại
    là sai."""
    thay: list[str] = []
    for x in v:
        if x not in thay:
            thay.append(x)
    return thay


class TaoVaiTroIn(BaseModel):
    name: Annotated[str, AfterValidator(_lam_sach_ten)]
    description: str | None = None
    actions: Annotated[list[str], AfterValidator(_bo_trung)]


class SuaVaiTroIn(BaseModel):
    """`actions` là THAY THẾ TOÀN BỘ, không cộng dồn — spec §4, cùng lý lẽ M2b §4.4.

    Form là 13 checkbox người dùng sửa trực tiếp. Diễn dịch nó thành chuỗi
    add/remove ở FE là đặt logic hoà giải vào chỗ không có transaction, và hai
    tab mở cùng lúc sẽ trộn ra một tập quyền không ai chọn.
    """

    name: Annotated[str, AfterValidator(_lam_sach_ten)]
    description: str | None = None
    actions: Annotated[list[str], AfterValidator(_bo_trung)]
