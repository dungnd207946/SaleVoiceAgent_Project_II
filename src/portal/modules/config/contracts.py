"""MẶT TIỀN của module config — file DUY NHẤT module khác được import.

Import `service.py` / `repo.py` / `router.py` từ module khác là LỖI CI
(tests/test_module_boundaries.py đọc AST, không phải quy ước trong đầu ai).

`ConfigPayload` là NGUỒN SỰ THẬT DUY NHẤT của hình dạng cấu hình agent. Màn Agent
Studio dựng form từ đúng model này qua `contracts/openapi.json`; `agent_config.py`
dịch đúng model này xuống bảng phẳng. Một nguồn — nên form và bảng không có đường lệch nhau.

VÌ SAO TÊN TRƯỜNG TIẾNG VIỆT: đây là hợp đồng giữa portal và MÀN HÌNH của nó, và
toàn bộ nghiệp vụ ở đây là tiếng Việt. Nó KHÔNG phải hợp đồng với agent: agent
(`AGENT_CONFIG_SOURCE=db`) đọc bảng phẳng `tenant_data.agent_config`, đầu ra của
`agent_config.hang_phang()`. Đổi payload này thì sửa cả `hang_phang()` lẫn chiều
ngược `tu_hang_phang()` — `GET /config` dựng payload từ bảng phẳng (từ `0966` không
còn `config_drafts` giữ bản gốc).

BA TẦNG QUYỀN SỬA (AG_01 BR01) — chỉ tầng (c) ở đây:
  (a) Khoá        — 110 dòng cơ chế. KHÔNG ở file này, không endpoint nào chạm
  (b) Sinh tự động — danh mục kỹ năng, sinh từ `tools.enabled` lúc render
  (c) Tenant điền  — 9 ô + 2 preset. ĐÂY.
Sáu rào chắn thuộc (a): có mặt trong payload nghĩa là có đường tắt bằng một
request, và AG_01 BR08 gọi đó là bán một công tắc gây sự cố.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from portal.modules.config.tools import TEN_KY_NANG, thieu_phu_thuoc

SCHEMA_VERSION_HIEN_TAI = 3
"""v1 (M3) có đúng 2 biến để chứng minh đường ống; v2 mở đủ 9 ô của AG_01; v3 tách
`xung_ho` thành `tu_xung` + `goi_khach` (2026-08-06).

Từ `0966` KHÔNG còn hàng nào lưu số này: bảng phẳng `tenant_data.agent_config` không có
cột `schema_version`, và `GET /config` gắn đúng số hiện hành vào payload dựng ngược
(`agent_config.tu_hang_phang`). `PUT /config` từ chối (409 `CONFIG_SCHEMA_CU`) payload
khai số khác — kiểm TƯỜNG MINH ở `service.luu_cau_hinh`, vì field này là int trần.

Thêm ô mới về sau thì thêm `Field(default=...)` VÀ một cột ở `agent_config` (+ hai hàm
ánh xạ) — không có cột thì ô mới lưu xong đọc lại mất trắng. ĐỔI TÊN hoặc XOÁ ô thì nâng
số ở đây để FE cũ đang mở màn hình nhận 409 thay vì ghi đè bằng hình dạng cũ.
"""

GIONG_DIEU = ("lich_su", "than_thien", "ngan_gon")
DO_DAI = ("ngan", "trung_binh", "chi_tiet")
LINH_VUC = ("realestate",)
"""Danh sách ĐÓNG, không phải chuỗi tự do.

Ba preset giọng điệu do platform viết và kiểm thử (AG_01 BR07); nhận chuỗi tự do
là mở lại đúng cánh cửa BR02 đóng — tenant gõ một đoạn hướng dẫn vào ô "giọng
điệu" và nó đi thẳng vào prompt.
"""


class _Nghiem(BaseModel):
    """Từ chối trường lạ, ở MỌI tầng — không chỉ ở gốc.

    Chỉ chặn ở gốc thì `{"danh_tinh": {"prompt_tho": "..."}}` lọt qua. Và một
    trường lạ bị nuốt im lặng là chỗ FE gõ sai tên trường mà không ai biết cho
    tới lúc khách hỏi vì sao sửa mãi không thấy đổi.
    """

    model_config = ConfigDict(extra="forbid")


class PhongBan(_Nghiem):
    """Một đầu mối chuyển tiếp. AG_01: "Agent chuyển khách cho ai, theo loại vấn đề gì"."""

    ten: str = Field(min_length=1, max_length=60)
    khi_nao: str = Field(default="", max_length=200)


class DanhTinh(_Nghiem):
    ten_agent: str = Field(min_length=1, max_length=40)
    """AG_01 ER_01. Đây là tên agent tự xưng với khách."""
    ten_thuong_hieu: str = Field(min_length=1, max_length=80)
    """Mặc định lấy từ tên workspace — xem `payload_mac_dinh()`."""
    tu_xung: str = Field(default="em", min_length=1, max_length=20)
    """Agent tự gọi mình là gì. TÁCH KHỎI `goi_khach` từ schema v3.

    Trước v3 đây là MỘT ô `xung_ho` chứa cả cặp (`"em ↔ anh/chị"`). Một ô thì người
    điền phải tự nghĩ ra quy ước phân cách, và cái họ gõ đi thẳng vào persona: đã thấy
    `"em - anh/chị"`, `"em/anh chị"`, và cả một câu văn. Hai ô thì không còn quy ước
    nào để đoán sai, và agent dựng câu thay cho người dùng.

    `min_length=1` chứ không để rỗng lọt: chuỗi rỗng đi thẳng vào persona agent
    (cột `self_pronoun`) — câu agent nói với khách mất chủ ngữ. Không crash, nên không
    ai thấy; đúng loại tổn hại mà ô này tồn tại để tránh.
    """
    goi_khach: str = Field(default="anh/chị", min_length=1, max_length=20)
    """Agent gọi khách là gì. Xem `tu_xung` — kể cả lý do `min_length=1`."""
    loi_chao: str = Field(default="", max_length=200)


class PhamVi(_Nghiem):
    linh_vuc: Literal["realestate"] = "realestate"
    """MVP chỉ có bất động sản. Vertical lạ ⇒ cấu hình mà agent không có bộ kỹ năng
    tương ứng — và triệu chứng là agent trả lời bằng lời thay vì gọi tool."""
    lam_gi: str = Field(default="Tư vấn dự án và đặt lịch tham quan.", max_length=300)
    khong_lam_gi: str = Field(default="Hậu mãi và giá riêng — chuyển người thật.", max_length=300)
    phong_ban: list[PhongBan] = Field(min_length=1, max_length=8)
    """AG_01 ER_02: phải còn ít nhất một. Không có phòng ban thì khách bị bỏ rơi
    giữa cuộc — agent nhận ra mình không xử lý được mà không có ai để chuyển."""
    cau_tu_choi: str = Field(default="", max_length=200)
    """Rỗng ⇒ agent kéo về phạm vi tư vấn, không trích câu nào (`persona/RULES.md` bên agent)."""


class Giong(_Nghiem):
    giong_dieu: Literal["lich_su", "than_thien", "ngan_gon"] = "than_thien"
    do_dai: Literal["ngan", "trung_binh", "chi_tiet"] = "trung_binh"


class Tools(_Nghiem):
    enabled: list[str] = Field(min_length=1)
    """AG_01 ER_03: tắt hết ⇒ agent chỉ trò chuyện mà không tra được dữ liệu nào."""

    @model_validator(mode="after")
    def _kiem_ky_nang(self) -> "Tools":
        la = sorted(set(self.enabled) - TEN_KY_NANG)
        if la:
            raise ValueError(f"kỹ năng không tồn tại: {', '.join(la)}")

        thieu = thieu_phu_thuoc(self.enabled)
        if thieu:
            mo_ta = "; ".join(f"{ten} cần {can}" for ten, can in thieu)
            raise ValueError(f"thiếu kỹ năng phụ thuộc: {mo_ta}")
        return self


_KY_TU_DIEU_KHIEN = frozenset(chr(c) for c in range(32)) | {chr(127)}


class NormalizationEntry(_Nghiem):
    """Một mục của từ điển cách đọc TTS. `term` là khoá cần khớp, `read_as` là văn bản thay ra."""

    term: str = Field(min_length=1, max_length=60)
    read_as: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _kiem_muc(self) -> "NormalizationEntry":
        # Khoảng trắng ở mép làm `\b` bên agent không bao giờ khớp — mục vô hiệu, không lỗi.
        if self.term != self.term.strip():
            raise ValueError("term không được có khoảng trắng ở đầu hoặc cuối")
        if self.term == self.read_as:
            raise ValueError("term trùng read_as — mục này không làm gì")
        for ten, gia_tri in (("term", self.term), ("read_as", self.read_as)):
            if any(ch in _KY_TU_DIEU_KHIEN for ch in gia_tri):
                raise ValueError(f"{ten} chứa ký tự điều khiển")
        return self


class ConfigPayload(_Nghiem):
    schema_version: int
    """Có mặt TỪ HÀNG ĐẦU TIÊN. Các hàng `config_versions` bất biến — không có số
    này thì phải đoán bản cũ theo hình dạng của nó."""
    danh_tinh: DanhTinh
    pham_vi: PhamVi
    giong: Giong = Field(default_factory=Giong)
    tools: Tools
    tts_normalization: list[NormalizationEntry] = Field(default_factory=list, max_length=200)
    """Từ điển cách đọc TTS của tenant — lớp CHỒNG LÊN bộ nền trong repo agent, không thay nó.

    Danh sách chứ không phải dict: khoá trùng thành 422 tường minh thay vì bị JSON âm thầm
    lấy giá trị cuối, và thứ tự này là thứ tự người dùng thấy trên bảng.
    """

    @field_validator("tts_normalization")
    @classmethod
    def _khong_trung_term(cls, v: list[NormalizationEntry]) -> list[NormalizationEntry]:
        da_thay: set[str] = set()
        for muc in v:
            khoa = muc.term.casefold()
            if khoa in da_thay:
                raise ValueError(f"term trùng (không phân biệt hoa/thường): {muc.term}")
            da_thay.add(khoa)
        return v


KEY_ROLE_MAC_DINH = "customer"
"""Role mọi tenant luôn có và không xoá được (`0967`: trigger tạo nó cùng tenant, trigger
khác chặn xoá). Các role còn lại do workspace tự tạo trong `tenant_data.role_config`.
Agent tự nhận biết role qua hội thoại — Portal không truyền gì sang."""

SO_ROLE_TOI_DA = 10
"""Trần số role một tenant. Mỗi role là một tab trên `/agent` và một hàng cấu hình
agent phải phân biệt — quá mười thì cả người lẫn agent đều không còn phân biệt nổi."""


class LuuCauHinhIn(_Nghiem):
    """Body của `PUT /config` — cấu hình của MỌI role, một lần Lưu, một giao dịch.

    Tập khoá PHẢI trùng đúng tập role đang có (`service.luu_cau_hinh` kiểm, 409 nếu lệch):
    FE đặt chung một số trường cho mọi tab, và một lần Lưu thiếu role là cách để các hàng
    lệch nhau ở đúng những trường "chung". Lệch cũng là dấu hiệu màn đang mở đã cũ (tab
    khác vừa thêm/xoá role).
    """

    cauHinh: dict[str, ConfigPayload]


def _ten_role(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("tên role không được để trống")
    if len(v) > 40:
        raise ValueError("tên role tối đa 40 ký tự")
    return v


def _icon_role(v: str | None) -> str | None:
    if v is not None and not re.fullmatch(r"[a-z0-9_]{1,32}", v):
        raise ValueError("mã icon chỉ gồm a-z, 0-9, _ (tối đa 32 ký tự)")
    return v


class TaoRoleIn(_Nghiem):
    """Body của `POST /config/roles`. `key` do BE sinh từ `ten` (bất biến sau đó)."""

    ten: str
    saoChepTu: str | None = None
    """Key của role nguồn để chép cấu hình. None = role mới dùng bộ mặc định."""
    icon: str | None = None
    """MÃ icon của tab. BE chỉ kiểm hình dạng — bảng mã → hình là của FE (mã lạ thì FE tự
    chọn một hình), nên thêm hình mới không cần sửa BE."""

    @field_validator("icon")
    @classmethod
    def _chuan_icon(cls, v: str | None) -> str | None:
        return _icon_role(v)

    @field_validator("ten")
    @classmethod
    def _chuan_ten(cls, v: str) -> str:
        return _ten_role(v)


class SuaRoleIn(_Nghiem):
    """Body của `PATCH /config/roles/{key}` — đổi tên và/hoặc icon, `key` không đổi.
    Vắng khoá = giữ nguyên; phải có ít nhất một khoá."""

    ten: str | None = None
    icon: str | None = None

    @field_validator("ten")
    @classmethod
    def _chuan_ten(cls, v: str | None) -> str | None:
        return None if v is None else _ten_role(v)

    @field_validator("icon")
    @classmethod
    def _chuan_icon(cls, v: str | None) -> str | None:
        return _icon_role(v)

    @model_validator(mode="after")
    def _co_gi_do(self) -> "SuaRoleIn":
        if self.ten is None and self.icon is None:
            raise ValueError("phải có `ten` hoặc `icon`")
        return self


KY_NANG_MAC_DINH = [
    "find_project",
    "discover_projects",
    "get_document",
    "search_units",
    "kb_search",
    "booking",
    "update_customer",
    "send_media",
    "escalate",
    "analyze_projects",
]
"""Toàn bộ 10 kỹ năng, bật sẵn cho một workspace mới. Không còn ba tên đã merge
(get_project_overview/recommend_units/check_inventory — discover_projects/
search_units đã có trong danh sách, thay thế đủ vai trò cũ). Người dùng chốt: bật
full để agent dùng được ngay mọi năng lực thay vì phải vào `/agent`/
`/ky-nang-bds` bật tay từng cái; workspace nào cần tắt bớt thì tự tắt ở màn cấu
hình.

⚠️ `analyze_projects` NẰM TRONG mặc định theo yêu cầu tường minh của người dùng
(2026-09-09) — dù `tools.py` vẫn ghi cảnh báo "chưa an toàn cho tenant thật"
(role sandbox `agent_sql_ro` chưa chặn được contacts/conversations/dữ liệu chưa
published). Quyết định có ý thức, không phải sót cảnh báo — xem
docs/superpowers/plans/2026-09-09-merge-structured-data-tools-skills.md."""


def payload_mac_dinh(ten_workspace: str) -> ConfigPayload:
    """Cấu hình dùng được ngay cho một workspace mới. AG_01 §I.2.

    BE sinh mặc định chứ KHÔNG phải FE: gọi thẳng API bỏ qua giao diện vẫn phải
    ra một cấu hình chạy đúng, và hai chỗ cùng sinh mặc định là hai chỗ sẽ lệch.
    """
    return ConfigPayload(
        schema_version=SCHEMA_VERSION_HIEN_TAI,
        danh_tinh=DanhTinh(ten_agent="Trợ lý", ten_thuong_hieu=ten_workspace),
        pham_vi=PhamVi(phong_ban=[PhongBan(ten="CSKH", khi_nao="Khách hỏi việc ngoài phạm vi tư vấn")]),
        tools=Tools(enabled=list(KY_NANG_MAC_DINH)),
    )


async def bao_agent_doi(conn, tenant_id: str) -> int | None:
    """Module khác đổi thứ agent đọc lúc dựng runner (playbook: `tenant_data.kich_ban`) → đưa `agent_config` lên
    version mới dưới đúng khoá Lưu của config. None = tenant chưa có hàng cấu hình (agent chạy legacy).
    Import lười: `agent_config` / `service` import file này."""
    from portal.modules.config import agent_config, service

    await service._khoa_tenant(conn, tenant_id)
    return await agent_config.tang_version(conn, tenant_id)
