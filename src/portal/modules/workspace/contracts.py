"""MẶT TIỀN của module workspace — file DUY NHẤT module khác được import.

Import `service.py` / `repo.py` / `router.py` từ module khác là LỖI CI
(tests/test_module_boundaries.py đọc AST).

TÊN TRƯỜNG camelCase ANH, khác `modules/config` dùng tiếng Việt: đây là hợp đồng
control-plane cùng hạng với `modules/auth` (`WorkspaceOut`, `SessionOut`,
`TaoUserIn`), và FE đọc nó bằng cùng một lớp client. `modules/config` dùng tiếng
Việt vì payload ở đó là nghiệp vụ tư vấn bất động sản — không cùng loại.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaoWorkspaceIn(BaseModel):
    """Một ô. Không hơn.

    KHÔNG nhận `id` từ client dù `tenants.id` là text người đọc được: id đó là
    khoá cách ly dùng cho bốn việc (policy RLS · `TENANT_ID` của pod · đường dẫn
    `tenants/<id>/` trên kho tệp · collection `kb_<id>`) và nó đi thẳng vào câu
    `CREATE ROLE agent_<id>`. Cho client chọn nó là cho client chọn tên một role
    Postgres. Backend mint — xem `service.sinh_tenant_id`.

    KHÔNG nhận `orgId`: tầng tổ chức đã bỏ 2026-08-15. Người tạo được lấy từ
    phiên đã xác thực và ghi vào `tenants.created_by`.

    KHÔNG nhận `vertical`: MVP chỉ có `realestate`, và
    `ConfigPayload.pham_vi.linh_vuc` cũng là `Literal["realestate"]`. Thêm ô cho
    một danh sách một phần tử là bán một công tắc chưa có gì ở đầu kia.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    """80 khớp `tenants.name` (text, không giới hạn ở DB).

    Giới hạn ở tầng app vì tên này hiện trong switcher chân sidebar với
    `truncate` — một cái tên 500 ký tự không nổ ở đâu cả, nó chỉ làm mọi bảng có
    một dòng rộng bất thường.
    """


class WorkspaceTaoRaOut(BaseModel):
    """Đủ để FE chèn thẳng vào danh sách switcher rồi chuyển sang, không cần GET lại."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    lifecycle: str
    """Cột LƯU — ý chí của người vận hành ('active' | 'suspended' | 'closed')."""
    status: str
    """SUY RA, không lưu: hàm thuần của lifecycle + heartbeat + live_version.

    Workspace mới luôn là `provisioning` (chưa nhịp tim nào) — KHÔNG phải lỗi.
    Trả cả hai trường vì chúng trả lời hai câu hỏi khác nhau.
    """
    created_at: datetime = Field(serialization_alias="createdAt")


class WorkspaceSuaRaOut(BaseModel):
    """HAI trường, và cố ý KHÔNG dùng lại `WorkspaceTaoRaOut`.

    Hình dạng kia mang `status` — thứ SUY RA từ nhịp tim và `live_version`,
    hai cột thuộc bảng của module KHÁC. Đường tạo trả
    được nó vì workspace mới chắc chắn chưa có nhịp tim nào; đường đổi tên thì
    không: workspace đang chạy sẽ nhận `provisioning`, một câu trả lời SAI mà
    không có lỗi nào. Trả ít đi rẻ hơn trả sai.

    `id` có mặt dù client đã biết nó: nó là bằng chứng mã workspace KHÔNG đổi theo
    tên — thứ giao diện phải nói được ngay sau khi bấm Lưu.
    """

    id: str
    name: str


class SuaWorkspaceIn(BaseModel):
    """Đổi tên. MỘT ô, và cố ý không có ô thứ hai.

    KHÔNG nhận `id`: `tenants.id` bất biến. Nó là khoá cách ly dùng cho bốn việc
    (policy RLS · role `agent_<id>` · `tenants/<id>/` trên kho tệp · collection
    `kb_<id>` — xem `core/ten_tai_nguyen.py`), nên đổi nó là một cuộc di trú dữ
    liệu xuyên bốn kho, không phải một request `PATCH`.

    KHÔNG nhận `lifecycle`: đình chỉ và đóng là những hành động RIÊNG, mỗi cái có
    hệ quả và cửa quyền của nó. Nhận nó ở đây là mở đường xoá workspace qua một
    endpoint tên là «sửa tên».
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _khong_toan_khoang_trang(cls, v: str) -> str:
        """`min_length=1` MỘT MÌNH KHÔNG ĐỦ — "   " dài 3 ký tự và đi lọt.

        Lọt thì `service.sua()` `strip()` nó về chuỗi rỗng, DB nhận (cột `name` là
        `text` không ràng buộc), và switcher ở chân sidebar hiện một dòng không có
        chữ nào — không bấm trúng, không đọc được, không sửa lại được từ giao diện.

        Trả về bản ĐÃ `strip()`: chuẩn hoá ở BIÊN NHẬP, một chỗ duy nhất, cùng lối
        `service.chuan_hoa_email` của module auth.
        """
        v = v.strip()
        if not v:
            raise ValueError("tên workspace không được rỗng")
        return v
