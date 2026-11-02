"""Luật completeness KB BĐS ("đủ dữ liệu cho agent") — HÀM THUẦN, không I/O.

`docs/build_module_knowledgebase/02-knowledge-base.md` §3: *"Completeness ("thiếu
dữ liệu") = tính lúc publish/đọc theo luật của template (không lưu cột) — chặn
publish + badge UI."* `02a-real-estate-template.md` §7 đã CHỐT luật cụ thể của
`real_estate` (đây là câu hỏi N2 tài liệu đã trả lời, không phải quyết định của
Task 5): *"project cần name+region+overview; unit cần
price_vnd+area_built_m2+sale_status."*

⚠️ LỆCH TÀI LIỆU CÓ CHỦ Ý — luật `project` nay là NĂM trường, không phải ba như
`02a §7` (spec `2026-08-21-nap-data-qua-ui-design.md` §3.5). Lịch sử để đọc con
số: 2026-08-18 BỎ `overview` (lý do: văn xuôi biên tập viên viết sau, chặn
publish vì nó biến việc biên tập thành cửa chặn) — 2026-08-21 ĐƯA LẠI, cộng
`investor` + `product_scale`, và lý do cũ được gánh bởi một THƯỚC ĐO MỀM ở
frontend (`Độ hoàn thiện n/12`) thay vì bởi việc nới cổng.

Nguồn để chọn năm trường: `kb/directive/verticals/real_estate.py` khai đúng 11
trường của `projects` được biến thành văn bản cho agent đọc. Trường ngoài danh
sách đó (`sale_phase`, `developer`, `link_360`) có điền cũng không tới tay agent
nên không có lý do gác cổng.

⚠️ `amenities` NẰM trong 11 trường nhưng CỐ Ý ở NGOÀI cổng: đo trên Aurora dev
2026-08-21, nó rỗng ở **94/94** dự án đang published. Một cổng mà mọi thứ đều
không qua thì không còn phân biệt được gì — nó thôi là cổng, thành tiếng ồn.
Sửa `02a §7` khi có dịp; chỗ lệch nằm ở đây, không giấu.

VÌ SAO KHÔNG PHẢI MỘT BẢNG CẤU HÌNH: bản M4a cũ (đã xoá) dựng hẳn
`control.field_policy_live` — 56 hàng mô tả "trường nào bắt buộc" — vì hồi đó
luật này được xem là thứ TENANT tự cấu hình. Tài liệu mới đảo quyết định đó:
mỗi lĩnh vực có ĐÚNG MỘT bộ luật completeness, cố định trong code cùng lúc với
schema (`02` §9 — cơ chế template lĩnh vực khai completeness như một mục cố
định, không phải dữ liệu runtime). Một bảng cho một hằng số đã biết trước lúc
viết code là công thừa: thêm một vòng SELECT, một chỗ có thể lệch với schema
thật, để đổi lấy một khả năng cấu hình không ai cần ở phase này.

KHÔNG LƯU CỘT: completeness không phải trường trong DB, không phải giá trị
cache — nó là một PHÉP TÍNH thuần trên bản ghi vừa đọc, chạy lại mỗi lần
publish/đọc (router gọi hàm này tại chỗ). Không có job nền "tính trước rồi lưu",
nên không có nguy cơ cột cache lệch khỏi dữ liệu thật khi ai đó sửa trực tiếp
một trường mà quên chạy lại phép tính.
"""

from collections.abc import Mapping

__all__ = ["BAT_BUOC", "cot_cua", "thieu_truong"]

BAT_BUOC: dict[str, tuple[str | tuple[str, ...], ...]] = {
    "project": ("name", "region", "overview", "investor"),
    "unit": ("price_vnd", ("area_built_m2", "area_land_m2"), "sale_status"),
}
"""`project` = BỐN trường. Spec 2026-08-21 §3.5 khai năm, `product_scale` đã BỎ
(người dùng chốt 2026-08-25): nó là câu mô tả tự do («3 toà · 1.240 căn hộ»), không
phải dữ liệu agent tra cứu, nên chặn phát hành vì thiếu nó là chặn nhầm chỗ.

MỘT PHẦN TỬ LÀ TUPLE = «MỘT TRONG SỐ ĐÓ LÀ ĐỦ». Chỉ `unit` dùng, cho diện tích.

⚠️ `unit` KHÔNG còn nguyên văn `02a §7` (đổi 2026-08-25). `02a §7` viết
`price_vnd+area_built_m2+sale_status`, nhưng sản phẩm ĐẤT không bao giờ có diện
tích thông thuỷ — đo trên DB dev `aina_prod`: biệt thự/nhà phố/shophouse có
**0/5.133** căn mang `area_built_m2` và **5.133/5.133** mang `area_land_m2`. Cổng
cũ vì thế gắn cờ thiếu lên cả 5.133 căn, trong đó **4.189 căn đang published và
hoàn toàn bình thường** — nó kêu ở cả ca đúng lẫn ca sai, tức thôi phân biệt được
gì. Nó còn làm một căn biệt thự nhập TAY trên portal không tài nào phát hành
được.

VÌ SAO «MỘT TRONG» CHỨ KHÔNG PHẢI MỘT DANH SÁCH LOẠI-HÌNH-NÀO-DÙNG-CỘT-NÀO: danh
sách đó là bản chép thứ ba của ngữ nghĩa loại hình (sau CHECK ở `0400` và
`enums.ts`), và nó không thể đúng với loại lưỡng tính như `shophouse` — vốn có cả
bản thấp tầng (bán theo đất) lẫn bản khối đế chung cư (bán theo thông thuỷ). Mục
đích của cổng là «agent có một con số diện tích để nói», và cả hai cột đều thoả.

⚠️ Danh sách này phải khớp TỪNG CHUỖI với `BAT_BUOC.project` của
`odyssey-portal-frontend/src/features/realestate/completeness.ts` — bản FE chỉ
được phép nghiêm BẰNG hoặc LỎNG hơn, và không có cổng CI nào so hai bên.

CHỈ hai entity này có mặt:
`zone`/`document`/`media` không xuất hiện vì tài liệu không định nghĩa luật
completeness cho chúng (task-5-brief.md mục B: "đừng tự đặt thêm"). Entity nào
không có trong dict này thì `thieu_truong()` luôn trả rỗng — coi như "không có
luật thì không có gì để thiếu", không phải lỗi cấu hình thiếu sót."""


def cot_cua(entity: str) -> tuple[str, ...]:
    """Mọi CỘT mà cổng của `entity` chạm tới, đã trải phẳng nhóm một-trong.

    `_chan_publish_thieu` hỏi «payload này có chạm cổng không» bằng cách so tên cột;
    một nhóm một-trong là tuple, và đem tuple đi so với khoá chuỗi thì luôn sai mà
    không lỗi nào phát ra.
    """
    ra: list[str] = []
    for muc in BAT_BUOC.get(entity, ()):
        ra.extend((muc,) if isinstance(muc, str) else muc)
    return tuple(ra)


def _trong(gia_tri) -> bool:
    return gia_tri is None or gia_tri == ""


def thieu_truong(entity: str, ban_ghi: Mapping) -> list[str]:
    """Trả danh sách tên cột còn thiếu để `ban_ghi` (của `entity`) đủ dữ liệu
    cho agent đọc. Rỗng = đủ dữ liệu.

    `entity` không có luật trong `BAT_BUOC` (`"zone"`/`"document"`/`"media"`,
    hoặc bất kỳ chuỗi lạ nào) ⇒ luôn trả `[]`.

    "Thiếu" là MỘT phép kiểm tổng quát (`None` HOẶC chuỗi rỗng `""`), không phải
    hai nhánh kiểu riêng — kiểm bằng `information_schema` thật (không đoán, xem
    task-5-report.md) cho thấy đúng hai hình dạng cột ở migration
    `0400_kb_real_estate.py`, và phép kiểm chung này đúng cho CẢ HAI mà không
    cần biết trước đang xét cột nào:
      - `projects.name/region/overview` — `text NOT NULL DEFAULT ''`: giá trị
        không có KHÔNG BAO GIỜ là `NULL` (cột NOT NULL), luôn là `''` — nhánh
        `gia_tri == ""` bắt đúng trường hợp này.
      - `units.price_vnd/area_built_m2` — `numeric` NULLABLE, không DEFAULT:
        giá trị không có LUÔN là `None` — nhánh `gia_tri is None` bắt đúng.
      - `units.sale_status` — `text NOT NULL DEFAULT 'available'` + CHECK giới
        hạn enum: trên thực tế không bao giờ `None`/`''` (DB không cho phép),
        nhưng hàm vẫn kiểm tổng quát để đúng với MỌI cách gọi — kể cả
        `ban_ghi` dựng tay trong test (`sale_status=""`), không chỉ bản ghi
        thật lấy từ DB.
    """
    thieu: list[str] = []
    for muc in BAT_BUOC.get(entity, ()):
        if isinstance(muc, str):
            if _trong(ban_ghi[muc]):
                thieu.append(muc)
        elif all(_trong(ban_ghi[t]) for t in muc):
            # MỘT mục, không phải nhiều — hai mục đọc thành «phải điền cả hai».
            thieu.append(" hoặc ".join(muc))
    return thieu
