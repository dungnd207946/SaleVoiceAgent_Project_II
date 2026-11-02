"""MẶT TIỀN của module ingest — file DUY NHẤT module khác được import.

Import `repo.py` / `service.py` / `router*.py` từ module khác là LỖI CI
(`tests/test_module_boundaries.py` đọc AST).

Thiết kế: `docs/superpowers/specs/2026-08-14-cong-nap-du-lieu-ngoai-design.md`.

── HAI HỌ TÊN TRƯỜNG TRONG CÙNG MỘT MODULE, CÓ CHỦ ĐÍCH ─────────────────────
  · **Data-plane** (`BanGhiIn`, `LoNapIn`, `KetQuaBanGhi`…) — tên TIẾNG ANH
    (`entity`, `externalId`, `occurredAt`, `data`). Đây là hợp đồng mà adapter
    BÊN KHÁCH code vào, và nó xuất hiện trong Swagger của họ. Tiếng Việt ở đây là
    bắt một dev không nói tiếng Việt gõ `duLieu` vào payload.
  · **Control-plane** (`TongQuanOut`, `ThongKeOut`, `LoiNapOut`…) — tên TIẾNG
    VIỆT (`diemNap`, `thongKe`, `nhanCuoiLuc`). Đây là hợp đồng nội bộ với portal
    FE, cùng hạng `modules/config`, và FE đã đọc đúng những tên này.

⚠️ TÊN CONTROL-PLANE PHẢI KHỚP TỪNG KÝ TỰ với `features/realestate/nguon.ts` bên
FE. Không có cổng parity nào canh (FE là bản sao viết tay) — đổi một tên ở đây mà
quên bên kia thì màn trắng lúc chạy trong khi cả hai repo đều xanh. Đã xảy ra một
lần trong lúc thi công FE.
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "BanGhiIn",
    "BanKeIn",
    "DoiSoatOut",
    "MucBanKe",
    "Entity",
    "ENTITY_HOP_LE",
    "KetQuaBanGhi",
    "LoNapIn",
    "LoNapOut",
    "LoiNapOut",
    "TaoTokenIn",
    "ThongKeOut",
    "TokenOut",
    "TongQuanOut",
    "TrangLoiOut",
    "WhoamiOut",
    "DAI_NHAN_TOI_DA",
    "LINH_VUC",
    "PHIEN_BAN",
    "TRAN_LO",
]

Entity = Literal["project", "zone", "unit", "document", "media"]
"""5 thực thể KB BĐS — khớp `Entity` của `modules/realestate/contracts.py`."""

ENTITY_HOP_LE: tuple[str, ...] = ("project", "zone", "unit", "document", "media")

LINH_VUC = "realestate"

PHIEN_BAN = "v1"

DAI_NHAN_TOI_DA = 60

TRAN_LO = 500


# ─── Validator dùng chung ───────────────────────────────────────────────────


def _khong_nul(v: str | None) -> str | None:
    """Postgres từ chối NUL trong text (22P05) — chặn ở vỏ cho ra 422 field-level
    thay vì một câu 500 ở giữa lô."""
    if v is not None and "\x00" in v:
        raise ValueError("không được chứa ký tự NUL (\\u0000)")
    return v


# ─── Data-plane: thứ adapter bên khách gửi lên ───────────────────────────────


class BanGhiIn(BaseModel):
    """Một bản ghi trong lô. VỎ cố định + `data` theo thực thể.

    `extra="forbid"` Ở VỎ nhưng KHÔNG ở `data` — hai chỗ, hai luật, cố ý:
      · Vỏ sai chính tả (`externalID`, `occuredAt`) là lỗi phải nổ: bốn trường
        này là thứ duy nhất mình dùng để định danh và sắp thứ tự, gõ sai một cái
        là bản ghi đi lạc chứ không phải thiếu một field.
      · `data` thì NGƯỢC LẠI — trường lạ được BỎ QUA IM LẶNG (spec quyết định #3).
        Hệ thống bên khách sẽ mọc thêm cột theo thời gian; nếu mỗi lần như thế là
        một sự cố bên mình thì hợp đồng này giòn tới mức không dùng được.
    """

    model_config = ConfigDict(extra="forbid")

    entity: Entity
    externalId: str = Field(min_length=1, max_length=200)
    """Mã bản ghi BÊN KHÁCH — khoá duy nhất, không đổi theo thời gian.

    KHÔNG phải `project_code` của mình: mã đó Odyssey sinh (nó đi vào SQL của
    agent và tên chunk trên Qdrant nên định dạng phải do mình kiểm soát). Khách
    trỏ bản ghi con về cha bằng mã của chính họ — xem `projectExternalId`.
    """
    op: Literal["upsert", "delete"]
    occurredAt: AwareDatetime
    """Lúc thay đổi xảy ra BÊN KHÁCH — trọng tài của thứ tự.

    PHẢI mang múi giờ (offset hoặc Z) — bản naive từng bị diễn giải theo giờ HOST
    của server, tức trọng tài thứ tự đổi nghĩa theo máy deploy.

    KHÔNG dùng giờ nhận: sự kiện về lệch thứ tự là chuyện bình thường của đẩy bất
    đồng bộ, và giờ nhận nói về mạng chứ không nói về dữ liệu.
    """
    data: dict = Field(default_factory=dict)
    """Trường của thực thể. `op="delete"` thì bỏ trống được — mình chỉ cần
    `externalId` để biết xoá cái nào."""

    _v_external_id = field_validator("externalId")(_khong_nul)


class LoNapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[BanGhiIn] = Field(min_length=1, max_length=TRAN_LO)
    syncId: str | None = Field(default=None, max_length=200)
    """Chỉ để lần vết một lô trong nhật ký. Không tham gia vào phép nào."""

    _v_sync_id = field_validator("syncId")(_khong_nul)


class KetQuaBanGhi(BaseModel):
    """Kết quả của MỘT bản ghi. `status` có ba giá trị, không phải hai."""

    externalId: str
    status: Literal["accepted", "rejected", "stale"]
    """`stale` = `occurredAt` cũ hơn hoặc bằng bản đang có ⇒ bỏ qua.

    Tách khỏi `rejected` vì nó KHÔNG phải lỗi của bên khách: đẩy lại một sự kiện
    cũ là hành vi đúng của mọi cơ chế retry. Gộp hai cái làm bảng lỗi của họ đầy
    những dòng không cần sửa gì.
    """
    field: str = ""
    """Rỗng = lỗi ở cấp BẢN GHI, không cấp trường."""
    reason: str = ""


class LoNapOut(BaseModel):
    """`202` — nhận lô, kết quả TỪNG bản ghi.

    KHÔNG phải một mã cho cả lô: một bản ghi hỏng không được làm rớt 499 bản còn
    lại, và bên khách cần biết chính xác cái nào hỏng để đẩy lại đúng cái đó.
    """

    accepted: int
    rejected: int
    stale: int
    results: list[KetQuaBanGhi]
    dryRun: bool = False


class MucBanKe(BaseModel):
    """Một mục bản kê — HAI trường, không hơn.

    Không mang `op`: bản kê là ảnh chụp «những gì đang tồn tại bên tôi», nên thứ
    đã xoá đơn giản là không có mặt.
    """

    model_config = ConfigDict(extra="forbid")

    externalId: str
    updatedAt: AwareDatetime

    _v_external_id = field_validator("externalId")(_khong_nul)


class BanKeIn(BaseModel):
    """Bản kê đối soát của MỘT thực thể.

    Nhẹ có chủ ý: nó chạy hằng đêm trên TOÀN BỘ dữ liệu, nên phải rẻ hơn hẳn một
    lượt đẩy đủ — hai trường mỗi mục thay vì cả `data`.

    ⚠️ PHẢI ĐẦY ĐỦ cho KHOẢNG nó tự khai. Bản kê cắt dở mà không khai khoảng sẽ làm
    mọi bản ghi không nằm trong nó bị đánh dấu nghi mất tích — xem `doi_soat.py`.
    """

    model_config = ConfigDict(extra="forbid")

    entity: Entity
    records: list[MucBanKe]
    afterExternalId: str | None = None
    """Mã LỚN NHẤT **có trong `records` của trang trước**. `None` = trang đầu.

    ⚠️ ĐỌC KỸ CÂU TRÊN — «mã cuối của trang trước» có HAI nghĩa và chỉ một nghĩa
    đúng:

      · **mã lớn nhất ĐÃ GỬI**  ✅ đúng
      · mã lớn nhất ĐÃ QUÉT (kể cả bản ghi đã xoá bên khách nên không gửi)  ❌

    Chọn nghĩa thứ hai tạo ra một KHE IM LẶNG: bản ghi bị xoá nằm đúng ranh giới
    rơi ra ngoài cả trang trước (vì cận trên suy từ `max(records)`, không chứa nó)
    lẫn trang sau (vì cận dưới là HỞ) — không trang nào kiểm nó, và một `delete`
    bị rơi ở đó không ai phát hiện.

    Với nghĩa đúng thì không có khe: bản ghi đó lớn hơn mã cuối đã gửi, nên nó rơi
    vào khoảng của trang SAU và được kiểm ở đó. Đã đo.

    Đây là thứ làm hai trang liền nhau KHÔNG chừa khe: khoảng của trang này bắt đầu
    đúng chỗ trang trước kết thúc. Thiếu nó thì bản ghi nằm giữa hai trang không
    thuộc trang nào và vĩnh viễn không được kiểm.

    ⚠️ SẮP THEO THỨ TỰ BYTE (`sorted()` của Python, `ORDER BY … COLLATE "C"` của
    Postgres). Mình so bằng `COLLATE "C"`; sắp bằng thứ tự khác — collation có
    ngôn ngữ, không phân biệt hoa thường — làm ranh giới lệch, và bản ghi rơi vào
    trang không chứa nó sẽ bị gắn cờ SAI."""
    isLastPage: bool = True
    """Trang cuối ⇒ khoảng kéo tới +∞, tức mọi mã sau `afterExternalId` đều được
    kiểm. MẶC ĐỊNH `True` nên bản kê MỘT TRANG (hành vi trước 2026-08-15) vẫn đúng
    nguyên văn mà adapter không phải sửa gì — phân trang là phần THÊM.

    ⚠️ Không trang nào khai `isLastPage` thì đoạn sau mã lớn nhất KHÔNG BAO GIỜ được
    kiểm: một bản ghi bị xoá ở cuối không gian mã sẽ không ai phát hiện."""


class DoiSoatOut(BaseModel):
    dryRun: bool = False
    """`true` = lượt DIỄN TẬP: kết quả so là thật nhưng không cờ nào được gắn/gỡ,
    không nhật ký, không đóng dấu nhịp tim. Trường THÊM (mặc định `false`) —
    adapter cũ không đọc nó vẫn chạy nguyên văn, đúng luật `PHIEN_BAN`."""
    soLech: int
    """Hai bên lệch mốc ⇒ mình hụt một lần cập nhật ⇒ tự yêu cầu đẩy lại."""
    soNghiMatTich: int
    """Mình có, bản kê không có. **Không tự xoá** — một `delete` bị rơi và một bản
    ghi khách thật sự xoá trông giống hệt nhau ở phía mình, và đoán sai theo chiều
    xoá là mất dữ liệu không lấy lại được."""
    externalIdLech: list[str]
    externalIdNghiMatTich: list[str]


# ─── Control-plane: thứ portal FE đọc ───────────────────────────────────────


class TokenOut(BaseModel):
    """BA trường, không hơn — bảng bên FE có đúng hai cột (`Tên` · `Token`).

    KHÔNG có `keyPrefix` (chuỗi đầy đủ đã ở ngay đó, cách một cú bấm), KHÔNG có
    `status` (không tồn tại trạng thái vô hiệu — token còn trong bảng là token
    dùng được), KHÔNG có `createdBy`/`createdAt` (siêu dữ liệu kiểm toán là việc
    của Nhật ký). Người dùng chốt 2026-08-14 sau năm vòng cắt.
    """

    id: int
    label: str
    token: str


class ThongKeOut(BaseModel):
    nhanCuoiLuc: datetime | None
    soNhan24h: int
    soGhiDuoc24h: int
    soHong24h: int


class TongQuanOut(BaseModel):
    diemNap: str
    """URL đầy đủ khách POST vào. KHÔNG phải bí mật — nó là nửa còn lại của thứ
    bàn giao cho đội kỹ thuật bên kia."""
    docsUrl: str
    """Swagger của RIÊNG cổng nạp (`…/v1/docs`, `router.py` phục vụ) — không
    phải trang docs chung của portal. Backend trả về chứ không để FE ghép
    chuỗi: đường dẫn docs là thứ backend biết về chính nó."""
    thongKe: ThongKeOut
    tokens: list[TokenOut]


class WhoamiOut(BaseModel):
    """`GET /whoami` — token nạp tự hỏi «tôi đổ dữ liệu vào workspace nào?».

    Token ghim workspace lúc TẠO, và adapter bên khách chỉ cầm một chuỗi mờ —
    không có endpoint này thì cách duy nhất biết đích là đẩy thử một bản ghi
    rồi đi tìm nó bằng mắt. Ca thật (AINA 2026-08-18): khách tạo workspace mới
    nhưng token vẫn của workspace cũ — mọi lượt sync XANH với accepted=0 vì dữ
    liệu y hệt đã nằm ở chỗ CŨ, và không màn hình nào nói cho họ biết vì sao.
    """

    workspaceId: str
    workspaceName: str


class TaoTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=DAI_NHAN_TOI_DA)


class LoiNapOut(BaseModel):
    id: int
    entity: str
    externalId: str
    truong: str
    lyDo: str
    nhanLuc: datetime


class TrangLoiOut(BaseModel):
    loi: list[LoiNapOut]
