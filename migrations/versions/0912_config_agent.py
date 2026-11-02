"""config_versions.config_agent + view lộ shape §4 — agent tự render prompt

`config_agent` NULLABLE có chủ đích: các hàng `config_versions` là BẤT BIẾN (0200
`REVOKE UPDATE, DELETE`), nên KHÔNG backfill. Hàng v2 cũ giữ NULL, và view lộ
`schema_version` để agent báo được lỗi chính xác ("đang live ở v2, publish lại")
thay vì một `no published config` chung chung.

`schema_version` đọc từ `payload` chứ KHÔNG thêm cột: nó đã là trường bắt buộc
trong payload từ hàng đầu tiên (contracts.py), thêm cột là bản sao thứ hai của
một sự thật.

⚠️ CHECK `config_versions_config_agent_tu_v3` — vì sao cần dù `repo.them_version()`
đã có tham số `config_agent`: kiểu tham số vẫn là `dict | None`, nên KHÔNG có gì ở
tầng Python ngăn một caller tương lai gọi mà quên truyền. Hậu quả im lặng nếu
thiếu CHECK này: một hàng v3 với `config_agent = NULL` làm view trả
`config = NULL, schema_version = 3` — và cổng phía agent (từ chối khi
`schema_version ≠ 3`) sẽ CHO QUA, vì schema_version vẫn đúng 3. Agent nhận cấu
hình rỗng thay vì bị chặn. CHECK ở tầng DB vì đây đúng loại bất biến DB được sinh
ra để giữ — không phụ thuộc caller nào nhớ đúng, không phụ thuộc cổng phía agent
có thật sự fail-loud hay không.

Hàng v1/v2 (schema < 3) không bị đòi `config_agent`: chúng ghi TRƯỚC khi
`sang_config_agent()` tồn tại, và bất biến 0200 cấm sửa lại. Đã kiểm tay: 3 hàng
`anphu` trên DB dev (`schema_version = 2`, `config_agent NULL`) thoả CHECK.

⚠️ CỘT `schema_version` ĐẶT SAU `config`, KHÔNG PHẢI GIỮA `version` VÀ `config` NHƯ
BẢN NHÁP ĐẦU CỦA MIGRATION NÀY (và của spec §4.1): đã kiểm chứng bằng tay trên DB
dev — `CREATE OR REPLACE VIEW` cấm đổi TÊN một cột đang tồn tại ở đúng vị trí đó
(view hiện tại là cột 3 = `config`); chèn `schema_version` vào giữa đổi tên cột 3
thành `schema_version`, và Postgres từ chối với "cannot change name of view column
"config" to "schema_version"". Chỉ được PHỤ THÊM cột mới ở CUỐI. Không ảnh hưởng
người đọc: mọi nơi trong repo này lẫn phía agent đều SELECT theo TÊN cột
(`SELECT version, schema_version, config FROM ...`), không theo vị trí.
"""

from alembic import op

revision = "0912_config_agent"
down_revision = "0911_tenant_id_gach_ngang"
branch_labels = None
depends_on = None


SQL_TACH_XUNG_HO = """
UPDATE control.config_drafts d
   SET payload = jsonb_set(
           jsonb_set(
               d.payload,
               '{danh_tinh}',
               (COALESCE(d.payload -> 'danh_tinh', '{}'::jsonb) - 'xung_ho') || jsonb_build_object(
                   'tu_xung',
                   COALESCE(NULLIF(d.payload -> 'danh_tinh' ->> 'tu_xung', ''), btrim(split_part(t.doi, '↔', 1))),
                   'goi_khach',
                   COALESCE(NULLIF(d.payload -> 'danh_tinh' ->> 'goi_khach', ''), btrim(split_part(t.doi, '↔', 2)))
               )
           ),
           '{schema_version}', '3'::jsonb
       ),
       schema_version = 3
  FROM (
        SELECT tenant_id,
               CASE WHEN payload -> 'danh_tinh' ->> 'xung_ho' LIKE '%↔%'
                    THEN payload -> 'danh_tinh' ->> 'xung_ho'
                    ELSE 'em ↔ anh/chị'
               END AS doi
          FROM control.config_drafts
         WHERE schema_version < 3
       ) t
 WHERE d.tenant_id = t.tenant_id
"""
"""Bản nháp v1/v2 → v3: tách `danh_tinh.xung_ho` thành `tu_xung` + `goi_khach`.

VÌ SAO CÓ PHÉP NÀY. `config_drafts` là bảng MUTABLE — 0200 chỉ `REVOKE UPDATE,
DELETE` trên `config_versions`. Và một hàng nháp v2 tồn dư làm màn Agent Studio
KHÔNG DÙNG ĐƯỢC, vĩnh viễn, không có đường ra từ UI: `GET /config/draft` trả
payload nguyên văn, FE nạp thẳng vào form, `tu_xung`/`goi_khach` là `undefined`,
và mọi `PUT /config/draft` sau đó vẫn mang `xung_ho` ⇒ `extra="forbid"` ⇒ 422.
Đo được trên DB dev: tenant `anphu` đúng là một hàng như vậy.

ĐÂY LÀ PHÉP TÁCH CHUỖI MỘT LẦN, KHÔNG PHẢI CƠ CHẾ CHẠY DÀI. `contracts.py` nói rõ
vì sao ô `xung_ho` gộp bị bỏ: nó "buộc tầng dưới phải tách chuỗi — một phép tách
có thể sai âm thầm". Lý lẽ đó vẫn đúng, và nó nói về đường ghi THƯỜNG XUYÊN. Ở
đây chấp nhận được vì ba điều: nó chạy ĐÚNG MỘT LẦN, trên dữ liệu NHÁP (bản đang
làm việc, chưa publish, người dùng còn nhìn thấy và sửa được), và nó KIỂM ĐƯỢC
(`tests/modules/config/test_schema.py::test_migration_0910_*`).

BỐN QUYẾT ĐỊNH TRONG SQL NÀY:
· Không có `↔` (hoặc không có `xung_ho`) ⇒ CẶP MẶC ĐỊNH `em`/`anh/chị`, chứ không
  đoán một vế: `xung_ho = "con"` không nói được đó là vế tự xưng hay vế gọi khách,
  và đoán sai là agent gọi khách bằng "con". Hiện bằng literal `'em ↔ anh/chị'`
  để luật đọc là thấy.
· `COALESCE(NULLIF(... ->> 'tu_xung', ''), ...)` — GIỮ giá trị đã có, chỉ suy khi
  thiếu. `ConfigPayload.schema_version` là `int` trần, nên một client gửi tên
  trường v3 kèm `schema_version: 2` vẫn được nhận và lưu ở cột 2; đè giá trị tốt
  đó bằng mặc định là chính con lỗi mất trường mà nhánh này đang chữa.
· `COALESCE(d.payload -> 'danh_tinh', '{}')` — hàng không có `danh_tinh` (payload
  `{}` chèn bằng tay) không làm migration ném: `jsonb_set` là strict, một NULL ở
  đây thành `payload = NULL` và vi phạm NOT NULL. Hàng đó vốn đã không phải
  `ConfigPayload` hợp lệ; migration không có nhiệm vụ làm nó hợp lệ, chỉ có nhiệm
  vụ không chết.
· Ghi CẢ `payload->>'schema_version'` VÀ cột `schema_version`: hai bản sao của
  cùng một sự thật đã tồn tại từ 0200, và để lệch nhau thì `_ban_nhap_schema_cu()`
  (đọc cột) và cổng phía agent (đọc payload) nói hai chuyện khác nhau.
"""


KY_NANG_DA_KHAI_TU: tuple[str, ...] = ("get_project_financial",)
"""Danh sách ĐÓNG các tên kỹ năng đã bị gỡ khỏi sổ (`modules/config/tools.py`,
commit `8089341`) NHƯNG có thể còn tồn dư trong `config_drafts.payload` của
tenant nào đó lưu TRƯỚC lần gỡ.

KHÔNG đọc `MUOI_HAI_KY_NANG`/`TEN_KY_NANG` từ `portal.modules.config.tools`, và
KHÔNG import gì từ `portal.*`: một migration phải đóng băng đúng cái nó biết
lúc viết ra. Đọc sổ hiện hành nghĩa là mỗi lần sổ đổi (thêm/bớt kỹ năng), Ý
NGHĨA của migration NÀY đổi theo mà không ai sửa file này — một migration đã
chạy xong trên production kể một câu chuyện khác mỗi lần ai đó thêm kỹ năng mới.

Đo được trên DB dev: tenant `anphu` có cả bản nháp lẫn ba hàng `config_versions`
mang `get_project_financial` trong `tools.enabled`. Bản nháp là bản MUTABLE nên
dọn được (xem `SQL_DON_KY_NANG_DA_KHAI_TU`); ba hàng version thì BẤT BIẾN
(0200 `REVOKE UPDATE, DELETE`) và vô hại — chúng không tự validate lại,
`publish()` chỉ validate bản LIVE hiện tại, và nếu một ngày `ConfigPayload`
được validate lại từ đó thì `except ValidationError` ở `service.py::publish()`
đã dung thứ sẵn.
"""

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
"""Gỡ TÊN KỸ NĂNG ĐÃ KHAI TỬ khỏi `config_drafts.payload.tools.enabled`, giữ
nguyên thứ tự các tên còn lại.

VÌ SAO CÓ PHÉP NÀY, RIÊNG VỚI TỔ TÊN NÀY — không dùng chung nhánh với
`SQL_TACH_XUNG_HO`: đo được bằng vòng HTTP thật trên tenant `anphu` (DB dev),
SAU KHI `SQL_TACH_XUNG_HO` đã chuẩn hoá schema_version = 3. `GET /config/draft`
vẫn 200 (đọc không validate), nhưng `PUT /config/draft` với ĐÚNG payload đó trả
422 ("kỹ năng không tồn tại: get_project_financial") vì `Tools._kiem_ky_nang`
kiểm theo sổ HIỆN HÀNH — đúng sổ đã gỡ tên này ở commit `8089341`. Tenant không
lưu lại được form của chính mình, và không có nút nào trên Agent Studio gỡ một
tên kỹ năng ẩn (`nhan` mới hiện những tên CÒN trong sổ).

`?|` (bên phải) lọc TRƯỚC — chỉ những hàng thật sự mang một tên đã khai tử mới
bị UPDATE. `WHERE ten NOT IN (...)` (bên trong) mới là phép gỡ. `WITH
ORDINALITY` + `ORDER BY thu_tu`: `jsonb_array_elements_text` không tự hứa giữ
thứ tự qua một vòng lọc, và thứ tự kỹ năng là thứ tenant tự sắp trên UI — đảo nó
là một thay đổi tenant không hề bấm.

**MẢNG RỖNG SAU LỌC: ĐỂ RỖNG, KHÔNG BỊA CẤU HÌNH.** Một tenant mà TOÀN BỘ kỹ
năng đã bật đều là tên khai tử (không quan sát được ở `anphu`, nhưng không loại
trừ) sẽ có `tools.enabled = []` sau phép này — bản nháp đó chưa hợp lệ theo
`ConfigPayload` (`Tools.enabled` đòi `min_length=1`), và tenant phải tự mở màn
Agent Studio bật lại kỹ năng rồi Lưu. Migration không có danh sách kỹ năng nào
đúng để bịa thay tenant — bịa một bộ mặc định vào bản nháp của người khác còn
tệ hơn để họ tự sửa. `publish()` sẽ từ chối một bản nháp rỗng bằng 409 (xem
`service.BanNhapKhongHopLe`), không phải 500 — đó là lưới an toàn cho đúng
tình huống ô này để lại.

KHÔNG CHẠM `config_versions`: bảng đó BẤT BIẾN (0200), và ba hàng `anphu` mang
tên khai tử này vô hại — xem docstring của `KY_NANG_DA_KHAI_TU`.
"""


def upgrade() -> None:
    op.execute("ALTER TABLE control.config_versions ADD COLUMN config_agent jsonb")
    op.execute("ALTER TABLE control.agent_heartbeats ADD COLUMN skeleton_sha text")
    # NOT VALID — ép hàng MỚI, tha hàng CŨ, và đó là lựa chọn chứ không phải nhân nhượng.
    #
    # Ràng buộc này sinh ra khi v3 và cột `config_agent` còn là một: chưa thể có hàng v3
    # nào trước nó. Giả định đó chết ngày `0911_tenant_id_gach_ngang` — develop đã nâng
    # `SCHEMA_VERSION_HIEN_TAI` lên 3 ở một nhánh khác, nên mọi môi trường có người bấm
    # «Lưu và áp dụng» trong khoảng giữa hai lần deploy đều mang hàng v3 với
    # `config_agent IS NULL`. Đo được: DB dev local có 3 hàng như vậy, và migration
    # VỠ khi áp — cả chuỗi rollback, không ai lên được `head`.
    #
    # Vì sao KHÔNG backfill: `config_versions` bất biến (0200 `REVOKE UPDATE, DELETE`), và
    # backfill nghĩa là chép `sang_config_agent()` sang SQL. Hai bản dịch thì có ngày lệch,
    # và một bản dịch lệch âm thầm tệ hơn nhiều một ô NULL — NULL làm agent ném
    # `ConfigShapeError`, nhịp tim báo degraded, người vận hành thấy ngay.
    #
    # Cái giá đã nhận: hàng v3 xuất bản trong khoảng giữa đó không phục vụ được cho tới
    # khi tenant bấm «Lưu và áp dụng» lần nữa — một cú bấm, và bản mới có `config_agent`.
    op.execute(
        """
        ALTER TABLE control.config_versions
          ADD CONSTRAINT config_versions_config_agent_tu_v3
          CHECK (config_agent IS NOT NULL OR (payload->>'schema_version')::int < 3)
          NOT VALID
        """
    )
    # CREATE OR REPLACE (không DROP): giữ nguyên GRANT SELECT ... TO agent_all mà 0904 đã
    # cấp — dropping view sẽ xoá ACL và làm `odyssey_agent` mất quyền đọc cho tới dòng GRANT
    # tiếp theo, một cửa sổ hở dù ngắn mà ta không cần chấp nhận ở đây.
    op.execute(
        """
        CREATE OR REPLACE VIEW agent_api.agent_published_config AS
        SELECT v.tenant_id,
               v.version,
               v.config_agent                       AS config,
               (v.payload->>'schema_version')::int  AS schema_version
          FROM control.config_versions v
          JOIN control.config_live    l ON l.tenant_id = v.tenant_id AND l.version = v.version
         WHERE v.tenant_id = portal.current_tenant()
        """
    )

    # ─── Dữ liệu: bản nháp v1/v2 tồn dư ─────────────────────────────────────
    # Chạy SAU khi cột + constraint đã lên. Xem docstring của SQL_TACH_XUNG_HO cho
    # lý lẽ đầy đủ — tóm gọn: không có phép này thì tenant `anphu` trên DB dev không
    # mở được màn Agent Studio, và không có đường sửa nào từ giao diện.
    op.execute(SQL_TACH_XUNG_HO)

    # ─── Dữ liệu: tên kỹ năng đã khai tử tồn dư ──────────────────────────────
    # Chạy SAU bước xưng hô ở trên — không phụ thuộc nhau (đụng hai nhánh jsonb
    # khác nhau của cùng payload) nhưng cùng một loại phép: dọn dữ liệu MUTABLE
    # để form còn mở được. Xem docstring của SQL_DON_KY_NANG_DA_KHAI_TU.
    op.execute(SQL_DON_KY_NANG_DA_KHAI_TU)


def downgrade() -> None:
    # KHÔNG dựng lại `danh_tinh.xung_ho`. Phép tách ở upgrade() là MỘT CHIỀU, và
    # chấp nhận được vì gộp lại không khôi phục được gì: sau khi quay lui, người dùng
    # còn nhìn thấy bản nháp và sửa lại được hai ô — còn một `xung_ho` ta tự nối lại
    # từ hai vế đã bị mặc định hoá thì trông như dữ liệu tenant từng nhập mà không
    # phải. Ghi ra một sự thật bịa còn tệ hơn để trống một trường v2 đã hết dùng.
    #
    # CŨNG KHÔNG dựng lại các tên kỹ năng đã khai tử (`SQL_DON_KY_NANG_DA_KHAI_TU`
    # ở upgrade()) — MỘT CHIỀU, cùng lý lẽ: migration không giữ một bản sao "trước
    # khi lọc" của `tools.enabled`, nên "dựng lại" chỉ có thể là đoán, và đoán một
    # kỹ năng agent không có schema quay lại là tái tạo đúng con lỗi mà commit
    # `8089341` đã chữa.
    #
    # NGƯỢC LẠI với upgrade(): đây PHẢI là DROP + CREATE, không phải CREATE OR REPLACE.
    # Quay lui bỏ bớt cột `schema_version` (4 cột -> 3), và Postgres cấm CREATE OR REPLACE
    # VIEW rút bớt cột ("cannot drop columns from view") — đã kiểm tay trên DB dev. DROP
    # xoá luôn ACL của view nên phải GRANT lại đúng như 0904 đã cấp lúc tạo.
    op.execute("DROP VIEW agent_api.agent_published_config")
    op.execute(
        """
        CREATE VIEW agent_api.agent_published_config AS
        SELECT v.tenant_id, v.version, v.payload AS config
          FROM control.config_versions v
          JOIN control.config_live    l ON l.tenant_id = v.tenant_id AND l.version = v.version
         WHERE v.tenant_id = portal.current_tenant()
        """
    )
    op.execute("GRANT SELECT ON agent_api.agent_published_config TO agent_all")
    op.execute("ALTER TABLE control.config_versions DROP CONSTRAINT config_versions_config_agent_tu_v3")
    op.execute("ALTER TABLE control.agent_heartbeats DROP COLUMN skeleton_sha")
    op.execute("ALTER TABLE control.config_versions DROP COLUMN config_agent")
