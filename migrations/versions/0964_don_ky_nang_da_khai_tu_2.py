"""dọn 3 tên kỹ năng khai tử (merge 2026-09-09) khỏi config_drafts

Cùng lớp lỗi và cùng cách sửa với `0912_config_agent.py::SQL_DON_KY_NANG_DA_KHAI_TU`
(khi đó là `get_project_financial`) — đọc docstring ở đó trước khi đụng migration
này, đừng đoán lại từ đầu.

SỰ CỐ PHÁT HIỆN 2026-09-10 (production, tenant `aina_test`): `76be8f1` (2026-09-09)
gỡ `get_project_overview`/`recommend_units`/`check_inventory` khỏi
`modules/config/tools.py::TEN_KY_NANG`. Migration `0961_merge_tools_skills` đã
dọn `tenant_data.agent_config.skills` (bảng agent ĐỌC) nhưng KHÔNG đụng
`control.config_drafts.payload.tools.enabled` (bảng màn "Cấu hình chung" ĐỌC qua
`router.doc_ban_nhap()` → `service.doc_payload_cu()`). Hàng `config_drafts` nào
publish TRƯỚC 2026-09-09 mà chưa ai sửa lại từ đó vẫn mang 3 tên cũ trong mảng —
`ConfigPayload.model_validate()` ném `ValidationError` (`Tools._kiem_ky_nang`
kiểm theo sổ HIỆN HÀNH), `doc_payload_cu()` nuốt lỗi ĐÓ giống hệt lỗi "bản nháp
v2 tồn dư" (đúng thiết kế ban đầu của hàm, xem `service.py`), nên
`router.doc_ban_nhap()` trả `laMacDinh=True` + BỘ MẶC ĐỊNH — màn hiện như tenant
CHƯA CẤU HÌNH GÌ dù danh tính/phạm vi/giọng điệu/TTS thật vẫn nguyên trong DB.
KHÔNG mất dữ liệu (đường GHI không đụng tới) nhưng người xem không thấy được
dữ liệu thật, và nếu ai đó tưởng "chưa cấu hình" rồi bấm Lưu thì SẼ ghi đè thật.

Migration này KHÔNG sửa cơ chế đọc (đó là việc của `service.doc_payload_cu`,
xem PR sửa code kèm theo) — nó chỉ dọn DỮ LIỆU, đúng tinh thần "gộp rồi bỏ tên
cũ" của `0961`. `control.config_versions` (BẤT BIẾN, `0200` `REVOKE UPDATE,
DELETE`) KHÔNG đụng tới, và không cần đụng: `publish()` chỉ validate bản LIVE
lúc publish tiếp theo, không tự validate lại lịch sử; `except ValidationError`
ở đó đã dung thứ sẵn (xem docstring `0912`).
"""

from alembic import op

revision = "0964_don_ky_nang_da_khai_tu_2"
down_revision = "0963_project_hot_words"
branch_labels = None
depends_on = None

KY_NANG_DA_KHAI_TU: tuple[str, ...] = ("get_project_overview", "recommend_units", "check_inventory")
"""Đóng băng đúng ba tên đã gỡ ở `76be8f1` (2026-09-09) — KHÔNG import
`portal.modules.config.tools`, cùng lý do đã ghi ở `0912_config_agent.py`."""

_DANH_SACH_KHAI_TU_SQL = ", ".join(f"'{ten}'" for ten in KY_NANG_DA_KHAI_TU)

SQL_DON_KY_NANG_DA_KHAI_TU = f"""
UPDATE control.config_drafts
   SET payload = jsonb_set(
           payload,
           '{{tools,enabled}}',
           COALESCE(
               (SELECT jsonb_agg(ten ORDER BY thu_tu)
                  FROM jsonb_array_elements_text(payload -> 'tools' -> 'enabled') WITH ORDINALITY AS t(ten, thu_tu)
                 WHERE ten NOT IN ({_DANH_SACH_KHAI_TU_SQL})),
               '[]'::jsonb
           )
       )
 WHERE payload -> 'tools' -> 'enabled' ?| ARRAY[{_DANH_SACH_KHAI_TU_SQL}]
"""


def upgrade() -> None:
    op.execute(SQL_DON_KY_NANG_DA_KHAI_TU)


def downgrade() -> None:
    # Không phục hồi được — cùng lý do `0912`: không còn biết tenant nào từng có
    # tên nào trong ba tên đã gỡ trước khi UPDATE chạy.
    pass
