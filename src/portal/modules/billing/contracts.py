"""Mặt tiền module billing. Module khác chỉ được import từ file này (Luật 3)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

TRANG_MAC_DINH: Final = 50
TRANG_TOI_DA: Final = 200

NHAN_CHUA_PHAN_LOAI: Final = "Chưa phân loại (không có khoá)"
"""Nhãn cho nhóm agent_key_id IS NULL. Nhóm này KHÔNG được ẩn khỏi UI: ẩn nó là
làm tổng theo khoá lệch tổng hoá đơn, và lệch theo hướng thiếu nên không ai thấy."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanhBaoOut(_Base):
    """Ba con số vận hành. Khác 0 là có việc phải làm, không phải thông tin nền."""

    thieu_gia: int = Field(description="cặp (component, metric) có usage mà chưa có giá")
    nhan_chua_phan_loai: int = Field(description="purpose agent gửi mà chưa ai phân loại")
    event_khong_so_do: int = Field(description="event không có số đo nào ⇒ không tính được tiền")
    llm_khong_chinh_xac: int = Field(description="event llm có exact=false ⇒ đo THIẾU token")


class TongQuanOut(_Base):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    voice_sec: float = Field(description="thời lượng cuộc gọi (component='call') — KHÔNG cộng chéo component khác")
    so_phien: int
    so_key: int
    chi_phi: Decimal
    chi_phi_du_lieu_ngoai: Decimal = Field(description="phần của `chi_phi` do dữ liệu ngoài (purpose `kb_web`)")
    currency: str
    canh_bao: CanhBaoOut


class DongKeyOut(_Base):
    """Một khoá trong kỳ — bảng «Lượt dùng theo khoá» của `/billing`.

    Bảy trường `chi_phi_<component>` (`repo.theo_key()`) tách `chi_phi` của
    CHÍNH hàng này theo dịch vụ (LLM/TTS/STT/Embed/Cuộc gọi/VAD/Xác thực giọng).
    Trong một hàng, tổng bảy trường đó THƯỜNG bằng `chi_phi` — trừ khi hàng có
    usage của một component ngoài bảy mã đã biết, xem docstring `repo.theo_key()`.
    """

    agent_key_id: int | None = Field(description="None = nhóm chưa phân loại, hoặc dữ liệu ngoài")
    du_lieu_ngoai: bool = Field(description="hàng hệ thống: usage của dữ liệu ngoài, không thuộc khoá nào")
    label: str
    key_prefix: str
    nguoi_tao: str
    nguoi_tao_ten: str | None
    da_thu_hoi: bool
    so_phien: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    voice_sec: float
    so_event: int
    chi_phi: Decimal
    chi_phi_llm: Decimal
    chi_phi_tts: Decimal
    chi_phi_stt: Decimal
    chi_phi_embed: Decimal
    chi_phi_search: Decimal
    chi_phi_call: Decimal
    chi_phi_vad: Decimal
    chi_phi_speaker_verify: Decimal


class DanhSachKeyOut(_Base):
    items: list[DongKeyOut]
    total: int
    chi_phi_tong: Decimal
    currency: str


class PhanNgayOut(_Base):
    """Một component trong MỘT NGÀY. Chỉ những component thực sự phát sinh tiền
    ngày đó mới có hàng — không đệm 0 cho đủ bộ."""

    component: str
    chi_phi: Decimal


class DongNgayOut(_Base):
    """Một ngày của kỳ. Ngày KHÔNG có usage vẫn có hàng (`chi_phi = 0`, `phan`
    rỗng) — xem `repo.theo_ngay()` để biết vì sao khoảng trống không được bỏ
    trắng. `chi_phi` = tổng `phan`, tính ở router từ CÙNG những hàng đó nên hai
    số không có đường nào lệch nhau."""

    ngay: date
    chi_phi: Decimal
    phan: list[PhanNgayOut]


class DongComponentOut(_Base):
    """Một component trong kỳ: SỐ ĐO (từ `usage_events`) + TIỀN (từ `rated_usage`).

    `chi_phi = 0` KHÔNG có nghĩa là không dùng — nó nghĩa là chưa có dòng giá
    nào khớp component này (nằm trong `canh_bao.thieu_gia`), hoặc purpose của
    nó `billable = false`. Client phải phân biệt hai thứ đó khi trình bày.

    ⚠️ KHÔNG cộng các cột số đo lại với nhau qua nhiều component. `audio_sec`
    của `vad`/`stt`/`call` đo những quãng CHỒNG LẤN — chỉ `chi_phi` cộng được.
    """

    component: str
    so_event: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    audio_sec: float
    text_units: int
    units: int
    chi_phi: Decimal
    chi_phi_du_lieu_ngoai: Decimal


class PhanTichOut(_Base):
    """`GET /billing/breakdown` — mục ② «Tiền đi đâu»: trái theo NGÀY, phải theo
    COMPONENT. Cùng kỳ, cùng tổng với `/billing/summary`, chỉ khác chiều gộp.

    MỘT endpoint cho hai chiều chứ không hai: chúng luôn hiện cùng nhau trong
    một băng, luôn cùng khoảng ngày, và tách ra là hai request phải chờ nhau
    rồi hai trạng thái tải rời nhau trên cùng một hàng thẻ.
    """

    theo_ngay: list[DongNgayOut]
    theo_component: list[DongComponentOut]
    chi_phi_tong: Decimal
    currency: str


class PhanUsageNgayOut(_Base):
    """SỐ ĐO của một component trong MỘT ngày — không có cột tiền nào.

    Đây là phần thân của `/billing/usage-by-day`, endpoint của màn `/usage`.
    Khác `PhanNgayOut` (cùng chiều ngày+component nhưng chở `chi_phi`) đúng ở
    chỗ đó, và sự khác biệt là cả lý do hai endpoint tách nhau: `/usage` trả
    lời «dùng bao nhiêu», `/billing` trả lời «tốn bao nhiêu tiền».

    ⚠️ KHÔNG cộng các cột số đo qua nhiều component. `audio_sec` của
    `vad`/`stt`/`call` đo những quãng CHỒNG LẤN nhau trong thời gian (xem
    docstring `repo.tong_quan()`) — cộng chéo ra một con số không tồn tại.

    HAI CỘT CUỐI LỌC THEO `purpose`, phần còn lại gộp cả component:
    · `wall_ms_stream`       = `wall_ms`    của riêng `purpose='stream'`
    · `text_units_hoi_thoai` = `text_units` của riêng `purpose='conversation'`
    Đây là hai vế của component `stt` mà `billing.pricing_basis` khai riêng
    (`stt/stream/wall_ms` và `stt/conversation/text_units`). Chúng có ở MỌI
    component vì SQL gộp theo `(ngày, component)` chứ không đặc cách `stt` —
    component nào không có `purpose` đó thì bằng 0.

    ⚠️ `wall_ms_stream` KHÁC `wall_ms` gộp: bên agent ghi `wall_ms` cho mọi
    event như một độ trễ xử lý, nên tổng cả component KHÔNG phải «thời gian
    stream mở». Xem bất biến 5 của `repo.usage_theo_ngay()`.

    ⚠️ `text_units_hoi_thoai` KHÔNG thay `text_units`: `text_units` là số đo
    chính của `tts`/`embed`; cột lọc này là vế ký tự ĐỘC LẬP của `stt`
    (migration `0948`). Cùng tên gốc, khác mẫu số — đừng dùng lẫn.
    """

    component: str
    so_event: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    audio_sec: float
    text_units: int
    units: int
    wall_ms_stream: float
    text_units_hoi_thoai: int
    token_du_lieu_ngoai: int
    """in + out + cache_read của purpose `kb_web`."""
    text_units_du_lieu_ngoai: int


class UsageNgayOut(_Base):
    """Một NGÀY của kỳ. `phan` RỖNG = ngày đã đo và không có usage nào.

    Ngày rỗng vẫn có mặt trong mảng, đó là bất biến của endpoint — xem
    docstring `repo.usage_theo_ngay()`.

    `so_phien` đếm `DISTINCT session_id` có usage trong ngày, CÙNG định nghĩa
    với `TongQuanOut.so_phien` (chỉ khác cửa sổ) nên tooltip của biểu đồ và dải
    KPI không nói hai số khác nhau về cùng một thứ.
    """

    ngay: date
    so_phien: int
    phan: list[PhanUsageNgayOut]


class UsageTheoNgayOut(_Base):
    """`GET /billing/usage-by-day` — nguồn DUY NHẤT của thẻ biểu đồ màn `/usage`.

    KHÔNG có `chi_phi`/`currency` ở bất kỳ tầng nào, có chủ ý: `/usage` là màn
    LƯỢNG. Client suy tổng kỳ · đỉnh · số ngày hoạt động từ chính chuỗi ngày
    này (tổng theo ngày = tổng cả kỳ) thay vì gọi thêm `/billing/breakdown` —
    hai nguồn cho một con số là hai chỗ để lệch nhau âm thầm.
    """

    theo_ngay: list[UsageNgayOut]


class DongOwnerOut(_Base):
    """Gộp theo người tạo khoá. Bộ cột LƯỢNG khớp ĐÚNG `DongKeyOut`.

    Sáu cột lượng (`so_phien` · ba cột token · `voice_sec` · `so_event`) thêm
    2026-08-24 để bảng «Lượt dùng chi tiết» của `/usage` đổi chiều gộp mà không
    đổi bộ cột — người dùng bấm từ «Khoá» sang «Người tạo» phải thấy lại đúng
    những cột vừa đọc.

    ⚠️ Gộp ở CLIENT thì không làm được: bảng khoá có phân trang, nên cộng theo
    `nguoi_tao` trên trang hiện tại ra tổng của một trang chứ không của một
    người — và nó sai âm thầm, đúng bằng phần khoá nằm ở trang sau.

    Bảy trường `chi_phi_<component>` (`repo.theo_owner()`) thêm 2026-08-27, cùng
    ý nghĩa như ở `DongKeyOut`: tách `chi_phi` của CHÍNH hàng này theo dịch vụ
    (LLM/TTS/STT/Embed/Cuộc gọi/VAD/Xác thực giọng) — bảng «Lượt dùng theo người
    tạo» của `/billing` giờ khớp bộ cột với bảng «theo khoá». Trong một hàng,
    tổng bảy trường đó THƯỜNG bằng `chi_phi`, cùng ngoại lệ (component ngoài bảy
    mã đã biết) đã ghi ở `DongKeyOut`.
    """

    user_id: str | None
    ten: str | None
    email: str | None
    du_lieu_ngoai: bool
    so_key: int
    so_phien: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    voice_sec: float
    so_event: int
    chi_phi: Decimal
    chi_phi_llm: Decimal
    chi_phi_tts: Decimal
    chi_phi_stt: Decimal
    chi_phi_embed: Decimal
    chi_phi_search: Decimal
    chi_phi_call: Decimal
    chi_phi_vad: Decimal
    chi_phi_speaker_verify: Decimal


class PhienUsageOut(_Base):
    """Một phiên — bảng «Lượt dùng theo phiên» của `/billing`, và hàng `phien`
    của `ChiTietPhienOut` (cùng field, `router._phien_out()` dựng cả hai).

    Bảy trường `chi_phi_<component>` (2026-08-27, `repo.liet_ke_phien()`/
    `repo.doc_phien()`) tách `chi_phi` của CHÍNH hàng này theo dịch vụ — cùng
    ý nghĩa và cùng bảy mã đã ghi ở `DongKeyOut`. Trong một hàng, tổng bảy
    trường đó THƯỜNG bằng `chi_phi`, cùng ngoại lệ (component ngoài bảy mã đã
    biết) đã ghi ở đó.
    """

    session_id: str
    agent_key_id: int | None
    key_label: str | None
    customer_name: str | None
    phone: str | None
    channel: str
    bat_dau: datetime | None
    so_turn: int
    input_tokens: int
    output_tokens: int
    voice_sec: float
    chi_phi: Decimal
    chi_phi_llm: Decimal
    chi_phi_tts: Decimal
    chi_phi_stt: Decimal
    chi_phi_embed: Decimal
    chi_phi_search: Decimal
    chi_phi_call: Decimal
    chi_phi_vad: Decimal
    chi_phi_speaker_verify: Decimal
    exact: bool


class DanhSachPhienOut(_Base):
    items: list[PhienUsageOut]
    total: int


class EventOut(_Base):
    event_id: int
    seq: int
    turn_idx: int | None
    component: str
    purpose: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    audio_sec: float
    units: int
    text_units: int
    exact: bool
    chi_phi: Decimal
    occurred_at: datetime


class ChiTietPhienOut(_Base):
    phien: PhienUsageOut
    events: list[EventOut]
    ghi_chu_turn: str = Field(
        default=(
            "turn_idx của dòng audio là xấp xỉ (TTS của lượt N nằm ở lô N+1). "
            "Tổng theo phiên luôn đúng; đừng dùng số theo từng lượt để đối chiếu tiền."
        )
    )


# ─── Màn admin bảng giá (Task 9) — xác thực bằng token quản trị nền tảng ────


class PhienBanGiaIn(_Base):
    """Tạo một bảng giá NHÁP. `status` luôn khởi đầu 'inactive' — `kich_hoat` ở
    `service.py` là chỗ DUY NHẤT bật 'active', và nó kiểm phủ giá trước khi bật."""

    code: str = Field(min_length=1, max_length=64)
    name: str = ""
    currency: str = Field(default="VND", pattern="^[A-Z]{3}$")


class DongGiaIn(_Base):
    """Một dòng giá. `purpose`/`provider`/`model` rỗng = áp cho MỌI giá trị
    (wildcard) — khớp đúng ngữ nghĩa DDL của `billing.price_item` ở `0943`."""

    component: str = Field(min_length=1)
    purpose: str = ""
    provider: str = ""
    model: str = ""
    metric: str = Field(min_length=1)
    unit_price: Decimal = Field(ge=0, alias="unitPrice")
    per_units: int = Field(default=1, gt=0, alias="perUnits")
    note: str = ""


class GanBoGiaIn(_Base):
    """Gán một bảng giá cho tenant từ một mốc hiệu lực.

    `effective_from` PHẢI tz-aware — cùng bài học `occurredAt` của module `ingest`
    (Change Log 2026-08-15): asyncpg encode datetime naive theo giờ HOST, và mốc
    này quyết định khoảng nào của `billing.tenant_price_version` áp cho usage nào.
    """

    price_version_id: int = Field(alias="priceVersionId")
    effective_from: datetime = Field(alias="effectiveFrom")

    @field_validator("effective_from")
    @classmethod
    def _phai_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("effectiveFrom phải có timezone (tz-aware), vd hậu tố 'Z'")
        return v
