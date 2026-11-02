"""Hình dạng dữ liệu của M10 — nguồn sự thật duy nhất.

Hợp đồng bàn giao cho bên agent: docs/contracts/dau-noi-agent.md §2. Đổi hình
dạng ở đây mà không cập nhật file đó là để bên agent code theo một tài liệu sai.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer

TENANT_ID_PATTERN = r"^[a-z][a-z0-9_-]{1,30}$"
"""Cùng `tenants_id_check` (0002, nới cho `-` ở 0911) và hai hàm role của 0005/0900.

VÌ SAO KHAI Ở TẦNG PAYLOAD: trước bản này `DeploymentIn.tenant_id` chỉ có
`min_length=1, max_length=64`, nên một tenant_id sai định dạng đi thẳng xuống
`control.dat_mat_khau_agent()` và trả về **500** kèm stacktrace asyncpg
(`RaiseError: tenant id không hợp lệ cho tên role: ...`). Mất một phiên truy lỗi
để đi từ stacktrace đó về tới regex trong một migration. Chặn ở đây là 422 nói rõ
định dạng, và tầng DB vẫn giữ nguyên guard của nó — đây là lớp thứ hai, KHÔNG
phải lớp thay thế.
"""


@dataclass(frozen=True)
class KhoaHopLe:
    """Kết quả tra khoá. Chỉ tồn tại cho khoá CHƯA thu hồi — repo.tra_khoa lọc sẵn."""

    tenant_id: str
    """Đọc THẲNG từ `control.agent_keys.tenant_id` (`0940`). Trước đó phải JOIN
    qua `control.deployments` — xem header migration về việc vì sao tầng trung
    gian đó rỗng nghĩa."""
    key_id: int
    """`control.agent_keys.id` của CHÍNH khoá vừa xác thực — không phải khoá bất kỳ
    của tenant. Một tenant có nhiều khoá, nên `tenant_id` KHÔNG suy ra được giá trị
    này. Đi ra ngoài dưới tên `agent_key_id` (RuntimeCredentialsOut)."""


class KhoTepOut(BaseModel):
    endpoint: str
    bucket: str
    access_key: str
    secret_key: SecretStr
    prefix: str
    """`tenants/<tenant_id>/` — cùng tiền tố mà chinh_sach_tien_to() mở. Bundle,
    media, tài liệu gốc đều nằm dưới đây. Một tiền tố, một policy."""

    @field_serializer("secret_key", when_used="json")
    def _lo_secret(self, v: SecretStr) -> str:
        """`when_used="json"` — response HTTP có giá trị THẬT, còn repr()/str() thì
        in '**********'. Đúng chỗ cần: pod PHẢI nhận được secret; log thì KHÔNG."""
        return v.get_secret_value()


class KbOut(BaseModel):
    url: str
    collection: str
    """Tên collection Qdrant, suy từ tenant_id bằng core.ten_tai_nguyen.ten_collection().

    MỘT collection (dense + sparse named vectors) — đúng thứ modules/kb đang tạo.
    Thiết kế KB có nói tới collection `_media` thứ hai; nó CHƯA được xây, nên
    `/runtime-credentials` không hứa cái chưa có.
    """
    public_web_collection: str = ""
    """Collection Qdrant chứa dữ liệu web công khai (hồ sơ dự án, thẻ lân cận, bản tin) CỦA RIÊNG
    tenant — `core.ten_tai_nguyen.ten_kho_web()` (`<tenant_id>_public_web`). Thêm 2026-10-05, additive:
    trước đó agent đọc một collection `public_web` dùng chung mọi tenant (đã bỏ). `api_key` ở dưới mở
    quyền đọc cho CẢ hai collection."""
    api_key: SecretStr | None = None
    """JWT chỉ-đọc trên `collection` và `public_web_collection` ở trên, hết hạn cùng `expires_at`.

    Đặt vào header `api-key` khi nối Qdrant. Trước 2026-08-15 trường này KHÔNG tồn
    tại và pod nối Qdrant không kèm gì — nghĩa là mọi pod đọc được collection của
    MỌI tenant, và Qdrant không có lớp nào tương đương RLS để đỡ. Xem
    `enrollment/qdrant_jwt.py`.

    `None` = môi trường này CHƯA cấu hình khoá ký (`QDRANT_API_KEY` rỗng) ⇒ Qdrant
    chưa cưỡng chế gì ⇒ nối không kèm khoá như cũ. Cố ý `None` chứ không phải chuỗi
    rỗng: một chuỗi rỗng gửi vào header trông như «đã có khoá» ở mọi log và mọi
    lượt debug, còn `None` thì nói đúng rằng chưa có.

    ⚠️ Pod PHẢI đọc trường này và dùng nếu khác `None`, KỂ CẢ trước ngày Qdrant bật
    cưỡng chế — đó là thứ làm bước bật khoá thành không gián đoạn. Xem
    `docs/contracts/dau-noi-agent.md` §"Bật xác thực Qdrant".
    """

    @field_serializer("api_key", when_used="json")
    def _lo_api_key(self, v: SecretStr | None) -> str | None:
        return None if v is None else v.get_secret_value()


class RuntimeCredentialsOut(BaseModel):
    """⚠️ CHỨA MẬT KHẨU. Cấm log, cấm trace, cấm APM span (G-10 của hợp đồng)."""

    tenant_id: str
    agent_key_id: int
    """`control.agent_keys.id` của khoá dùng ở header `Authorization` để gọi chính
    endpoint này. Agent ghi lại vào `tenant_data.conversations.agent_key_id` (0939)
    để mỗi phiên quy được về khoá đã tạo ra nó — `tenant_id` không đủ, vì một tenant
    cấp nhiều khoá. KHÔNG bí mật: là số thứ tự, không phải bản thân khoá.

    `deployment_id` ĐÃ BỎ khỏi response ở `0940`. Agent nhận nó là `int | None` ở
    mọi chỗ và không đường nào assert nó có giá trị, nên pod không vỡ; hệ quả duy
    nhất là heartbeat ngừng ghi cho tới khi Pha 2 đổi khoá `agent_heartbeats` sang
    `tenant_id`. Đánh đổi đã nêu rõ và đã chốt — xem spec 2026-08-19."""
    postgres_role: str
    """Role Postgres của tenant này (`agent_<tenant_id>`) — KHÔNG bí mật, chỉ là tên."""
    postgres_password: SecretStr
    """Mật khẩu suy dẫn (`bi_mat.dan_xuat`). Host/port/database KHÔNG nằm trong response
    này — cố ý: chúng giống nhau cho mọi tenant, agent tự cấu hình tĩnh bên họ (cùng
    tinh thần với `PORTAL_URL` — xem `docs/contracts/dau-noi-agent.md`)."""
    storage: KhoTepOut
    kb: KbOut
    expires_at: datetime
    """Mốc TUYỆT ĐỐI UTC, không phải TTL tương đối — pod không phải bù lệch đồng hồ."""

    @field_serializer("postgres_password", when_used="json")
    def _lo_mat_khau(self, v: SecretStr) -> str:
        return v.get_secret_value()


class SanSangDuLieu(BaseModel):
    """Chẩn đoán, ĐỌC THUẦN — không cache, không lưu thành trạng thái.

    Cấp phát xong KHÔNG có nghĩa agent nói được: workspace chưa publish dự án nào
    thì `tenant_data.projects`/`kb_files` trả 0 hàng, pod chạy sạch, và agent tư
    vấn bằng kết quả rỗng. Hỏng im lặng và trông như đang hoạt động. Hai con số
    này là cách duy nhất admin thấy được nó.
    """

    projects_published: int
    kb_chunks: int


class TenantVanHanhOut(BaseModel):
    """Một dòng của màn vận hành xuyên tenant (`GET /admin/tenants`).

    THAY `DeploymentOut` ở `0941`. Ba trường cũ (`id`, `endpoint`, `provisioned_at`)
    thuộc về hàng `control.deployments` — bảng đã bỏ. Phần đáng giá của màn này chưa bao
    giờ là số hiệu pod mà là hai khối chẩn đoán bên dưới, nên chúng giữ nguyên.
    """

    tenant_id: str
    name: str
    lifecycle: str
    so_khoa_con_song: int
    san_sang_du_lieu: SanSangDuLieu


class KhoaMoiOut(BaseModel):
    """Khoá thô xuất hiện ĐÚNG MỘT LẦN, ở đây. Không đường nào đọc lại được."""

    id: int
    api_key: str
    key_prefix: str


# ─── Đường owner workspace tự phát khoá (cổng phiên + WORKSPACE_ADMIN) ────────
#
# Ba model dưới đây phục vụ /agent/keys — CỔNG THỨ BA của module, xem
# router_tenant.py. Chúng cố ý KHÔNG dùng chung với ba model ở trên: đường admin
# nền tảng nhận `tenant_id` từ URL và nói chuyện xuyên tenant, còn đường này lấy
# tenant TỪ PHIÊN đã xác thực và không bao giờ đọc nó từ request.


class TaoKhoaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """`extra="forbid"` — gửi thêm `tenant_id` bị 422 chứ không bị làm ngơ:
    `tenant_id` KHÔNG được đến từ client, nó lấy từ phiên đã xác thực."""

    label: str = Field(default="", max_length=60)
    """Nhãn người dùng đặt, để phân biệt khoá lúc cần thu hồi đúng một cái.

    Rỗng là hợp lệ — bảng vẫn nhận ra khoá qua `key_prefix`. 60 ký tự vì cột là
    `text` không giới hạn, nhưng một nhãn dài hơn thế thì bảng không hiện hết."""


class DatTrangThaiKhoaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "inactive"]
    """Theo mô hình Anthropic Admin API — MỘT trường cho cả hai chiều bật/tắt,
    không phải hai hành động (`POST /keys/{id}` đi được cả hai chiều). Chỉ hai
    giá trị: khoá ở đây không có vòng đời lưu trữ nên `archived`/`expired` của
    Anthropic không có nghĩa — gửi giá trị khác bị 422."""


class KhoaOut(BaseModel):
    """Một hàng trong bảng khoá.

    `api_key` (từ `0918`) là khoá THÔ — CÓ trong response này, theo yêu cầu
    tường minh của người vận hành: `/thu-agent` (repo frontend) cần dựng
    `<select>` chọn khoá theo tên mà vẫn nối WS thật, và điều đó chỉ làm được
    nếu màn hình đọc lại được giá trị thô. Nghĩa là mỗi lần tải `/api-keys`
    hoặc `/thu-agent` là một lần khoá đi qua mạng — đánh đổi đã được ghi trong
    migration `0918`, không phải sơ suất. `None` cho khoá tạo TRƯỚC migration
    đó (không cách nào backfill ngược từ hash một chiều).
    """

    id: int
    api_key: str | None
    key_prefix: str
    label: str
    created_at: datetime
    last_used_at: datetime | None
    """None = khoá chưa gọi `/runtime-credentials` lần nào. FE hiện "Chưa dùng", không phải "—":
    hai thứ đó khác nhau và người đọc cần phân biệt được."""
    status: Literal["active", "inactive"]
    """`active` ⇔ `revoked_at IS NULL` — cùng vị từ mà `repo.tra_khoa()` dùng cho
    xác thực `/runtime-credentials`. Khoá TẮT không xoá hàng, chỉ ẩn khỏi đường
    đó; hàng vẫn liệt kê lại ở đây để bật lại được."""
    revoked_at: datetime | None
    """Lúc bị tắt. `None` khi `status == "active"`."""


class DanhSachKhoaOut(BaseModel):
    """Bọc list trong một object vì màn hình cần hai endpoint KỂ CẢ khi chưa có
    khoá nào — trạng thái rỗng vẫn phải hiện được endpoint để bàn giao.

    Hai trường TÁCH RIÊNG (không phải một `endpoint_url` + `kind`) vì FE hiện cả
    hai cùng lúc, không phải chọn giữa chúng — xem router_tenant.py."""

    endpoint_chat_url: str
    endpoint_voice_url: str
    keys: list[KhoaOut]


FEEDBACK_TRANG_MAC_DINH = 50
"""Số hàng một trang khi FE không truyền `limit` — đủ cho một màn feedback không
kéo nguyên bảng của tenant đang hoạt động lâu."""

FEEDBACK_GIOI_HAN_TRANG = 200
"""Trần cứng, cùng lý lẽ `realestate.contracts.GIOI_HAN_TRANG`: không có trần thì
`?limit=` lớn tuỳ ý biến phân trang thành trang trí."""


class FeedbackIn(BaseModel):
    """Body của `POST /agent/feedback`. KHÔNG có `tenant_id` — cố ý (xem router.py):
    tenant suy từ `Bearer api_key`, không tin bất kỳ giá trị nào client tự gửi."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)


class FeedbackOut(BaseModel):
    id: int
    session_id: str
    rating: int
    comment: str
    created_at: datetime
    #: Từ `tenant_data.conversations` cùng `(tenant_id, session_id)` — KHÔNG FK
    #: (agent có thể gọi feedback trước/độc lập với việc ghi conversations,
    #: cùng lý lẽ `conversation_messages`). `None` khi không có hàng khớp.
    customer_name: str | None
    phone: str | None
    #: Kênh phiên đến từ đâu — `conversations.source` (`'voice'`/`'chat'`, agent
    #: ghi: `base_session.py`/`telephony` → voice, `text_chat.py` → chat). Cột đó
    #: là `text` KHÔNG CHECK có chủ ý (`0916`: tập kênh chưa chốt, thêm kênh mới
    #: không được vỡ đường ghi) nên ĐỪNG hẹp kiểu này thành Literal ở đây —
    #: `Literal['voice','chat']` sẽ ném 500 đúng vào ngày agent gửi `zalo`.
    #: `None` = không có hàng `conversations` khớp, HOẶC agent bản cũ chưa gửi
    #: trường này. Hai ca đó FE xử lý như nhau: không vẽ chip, không đoán hộ.
    source: str | None


class DanhSachFeedbackOut(BaseModel):
    """Phân trang keyset theo `id DESC` (mới nhất trước). KHÔNG đục cursor như
    `realestate.contracts.ma_con_tro` — lộ `id` trần ở đây không mở ra gì: hàng
    đã bị RLS + `ACTIONS.CONVOS_READ` khoá vào đúng một workspace, và FE feedback
    không cần một hợp đồng cursor riêng cho một danh sách nhỏ, chỉ đọc."""

    items: list[FeedbackOut]
    next_before_id: int | None = None
    """Truyền lại làm `before_id` để lấy trang sau. `None` = hết trang."""
    total: int
    theo_sao: dict[str, int]
    """Khoá `"1".."5"`, LUÔN đủ 5 khoá (đếm 0 vẫn có mặt) — FE vẽ 5 thanh phân bố
    không phải tự lấp khoá thiếu. Tính trên TOÀN BỘ feedback của tenant, KHÔNG
    theo filter `rating`/`session_id` đang áp cho `items` (xem service)."""
    diem_trung_binh: float
    """Làm tròn 2 chữ số. `0.0` khi tenant chưa có feedback nào — KHÔNG `None`,
    vì FE hiện số này trực tiếp (`4.3`) và `None` buộc FE tự thêm nhánh rẽ cho
    một ca chỉ xảy ra lúc mới bắt đầu dùng tính năng."""


class KhoaDaTaoOut(BaseModel):
    """⚠️ Response CHỨA KHOÁ THÔ. Không log, không trace, không APM span (G-10).

    CỐ Ý KHÔNG có `label`/`created_at`: `service._phat_khoa` trả `KhoaMoiOut` và
    không trường nào trong hai cái đó có ở đấy. Thêm chúng là phải nới
    `KhoaMoiOut` — thứ đường admin cũng dùng — để phục vụ hai giá trị mà dialog
    KHÔNG hiện: nhãn thì người dùng vừa gõ, còn thời điểm tạo thì bảng phía sau
    refetch xong là có.

    Từ `0940` không model nào còn `deployment_id`, và `0941` bỏ hẳn bảng
    `control.deployments` — khái niệm "deployment" không còn tồn tại ở đâu cả.
    """

    id: int
    api_key: str
    key_prefix: str
    endpoint_chat_url: str
    endpoint_voice_url: str
    """Cả hai đi kèm khoá vì chúng luôn được bàn giao CÙNG NHAU. Tách ra là bắt FE
    ghép từ hai response, và một trong hai lần ghép sẽ sai."""


def _ha_tang():
    """Dựng `HaTang` — nạp muộn để `contracts` không kéo theo `minio` lúc import.

    Rẻ: chỉ dựng `MinioAdmin` từ cấu hình, không I/O nào.
    """
    from portal.modules.enrollment.ha_tang import HaTang

    return HaTang.tu_cai_dat()


async def xoa_role_agent_cua_tenant(conn, tenant_id: str) -> bool:
    """Xoá role Postgres `agent_<id>`. `False` = chưa từng cấp phát pod.

    MẶT TIỀN cho `modules/workspace` — nó không được import `ha_tang.py` (ruột module
    này), cổng `tests/test_module_boundaries.py` đọc AST và sẽ đỏ. Đặt ở đây chứ không
    ở `core/` vì đây là việc của M10: nó sở hữu vòng đời credential của pod.

    ⚠️ HAI HÀM RIÊNG, KHÔNG GỘP với `xoa_khoa_kho_tep_cua_tenant`. Bản đầu gộp cả hai
    vào một lời gọi, nên người gọi chỉ có MỘT `try` cho hai hệ khác nhau — và thông
    điệp lỗi phải viết "role và/hoặc access key", tức chính nó thừa nhận không biết
    cái nào hỏng. Ops đọc dòng đó sẽ đi kiểm một role đã biến mất. Đo được trên stack
    thật: MinIO trả 404 trong khi role đã xoá xong.

    GỌI SAU KHI hàng `control.tenants` đã bị xoá — hàm SQL cố ý không đòi tenant còn
    tồn tại, khác `create_agent_role`.
    """
    return await _ha_tang().xoa_role(conn, tenant_id)


def xoa_khoa_kho_tep_cua_tenant(tenant_id: str) -> bool:
    """Gỡ access key MinIO `agent-<id>`. `False` = không có gì để gỡ.

    KHÔNG dọn Qdrant — vòng đời collection thuộc `modules/kb` (xem docstring đầu
    `ha_tang.py`, luật đó không đổi). Người gọi phải gọi cả `kb.contracts` nữa.

    Ném khi MinIO từ chối hoặc không với tới được: lúc đó credential của workspace vừa
    xoá CÓ THỂ vẫn mở được kho tệp. "Key chưa từng tồn tại" thì KHÔNG ném — xem
    `HaTang.xoa_khoa_kho_tep`.
    """
    return _ha_tang().xoa_khoa_kho_tep(tenant_id)
