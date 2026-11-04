"""OpenAI tool schemas cho unified single-agent (Luna).

Mỗi description theo hướng operational-protocol: nêu KHI NÀO gọi + tool LÀM GÌ
+ 1 ví dụ câu khách nói. Rule vận hành sống ở definitions/RULES.md — không lặp
ở đây. `escalate` là off-ramp duy nhất (không có agent khác để hand off).
"""

from __future__ import annotations

import copy as _copy
import logging
import re as _re

logger = logging.getLogger("noble_agent.agent.tools.schemas")

# Valid `send_media.category` values (single source of truth — reused by the
# schema enum and by support_ops validation).
# Phải khớp `MEDIA_VISUAL_REAL_ESTATE` của Portal — đó là tập danh mục DUY NHẤT được nạp
# vào collection `_media`. `phap_ly` BỎ 2026-08-17: sau migration `0927` nó không còn là
# danh mục ảnh (pháp lý là một loại TÀI LIỆU, cùng nhóm với csbh) và CHECK của Portal từ
# chối nó. Để lại đây thì `send_media(category="phap_ly")` lọc theo một giá trị không point
# nào mang — luôn rỗng, im lặng. Hỏi giấy tờ pháp lý đi đường `kb_search`.
SEND_MEDIA_CATEGORIES = (
    "tong_quan",
    "ngoai_that",
    "noi_that",
    "tien_ich",
    "mat_bang",
    "vi_tri",
    "tien_do",
)

# Valid `send_media.content_type` values (single source of truth — reused by the
# schema enum and by support_ops validation).
# `tour_360` thêm 2026-08-14: Portal ghi link tour vào collection `_media` thay vì đặt link
# trong text của `_documents`, để LLM không phải chép lại một URL dài nhiều tham số.
SEND_MEDIA_CONTENT_TYPES = ("image", "video", "tour_360")

CUSTOMER_FIELDS = [
    "name",
    "gender",
    "phone",
    "project_interest",
    "purpose",
    "budget",
    "preferred_area",
    "bedroom_count",
    "is_buyer",
    "is_noble_customer",
    "noble_info",
    "full_name",
    "notes",
]

SCHEMAS: dict[str, dict] = {
    "update_customer": {
        "type": "function",
        "function": {
            "name": "update_customer",
            "description": (
                "Ghi nhớ thông tin cá nhân của khách vào hồ sơ: tên, giới tính, dự án đang quan tâm, "
                "mục đích ở hay đầu tư, ngân sách, khu vực muốn mua, số phòng ngủ. Gọi ngay khi khách "
                "vừa cung cấp bất kỳ thông tin nào trong số này. Ví dụ khách tự giới thiệu tên và nói tầm 3 tỷ "
                "thì gọi update_customer(name=<đúng tên khách vừa nói>, budget='3 tỷ'). Gộp MỌI field khách "
                "vừa cung cấp vào MỘT lời gọi — KHÔNG tách mỗi field một lời gọi. CHỈ ghi tên khách "
                "thực sự nói ra — không lấy tên từ ví dụ hay từ bất kỳ đâu khác."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Tên gọi khách vừa xưng (1–2 chữ cuối của họ tên), ghi đúng như khách nói.",
                    },
                    "full_name": {"type": "string", "description": "Họ tên đầy đủ nếu khách cung cấp."},
                    "gender": {
                        "type": "string",
                        "description": "Giới tính: M (nam/anh) hoặc F (nữ/chị).",
                        "enum": ["M", "F"],
                    },
                    "phone": {"type": "string", "description": "Số điện thoại (mười chữ số)."},
                    "project_interest": {
                        "type": "string",
                        "description": "Mã dự án canonical khách quan tâm (xem danh sách dự án {{ brand.company }}).",
                    },
                    "purpose": {"type": "string", "description": "Mục đích: ở, đầu tư, hoặc cả hai."},
                    "budget": {"type": "string", "description": "Ngân sách dự kiến."},
                    "preferred_area": {
                        "type": "string",
                        "description": (
                            "Khu vực khách MUỐN MUA (ghi đúng lời khách nói). KHÔNG phải nơi làm việc hay nơi "
                            "đang ở — những cái đó ghi vào notes."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": (
                            "Ghi chú bối cảnh ngắn để nhớ và tư vấn sát: nơi làm việc, số người ở cùng, con học "
                            "đâu, thời điểm dự kiến mua, băn khoăn chính. Gửi từng mẩu khi khách kể, hệ thống tự "
                            "cộng dồn. Ví dụ 'làm ở Long Biên, con sắp vào lớp 1'."
                        ),
                    },
                    "bedroom_count": {"type": "string", "description": "Số phòng ngủ (2PN, 3PN, ...)."},
                    "is_buyer": {
                        "type": "boolean",
                        "description": "True nếu khách đang tìm mua/đầu tư BĐS (không chỉ hỏi chơi).",
                    },
                    "is_noble_customer": {
                        "type": "boolean",
                        "description": "True nếu khách đã là khách {{ brand.company }} (đã mua / hợp đồng).",
                    },
                    "noble_info": {
                        "type": "string",
                        "description": "Ghi chú ngắn nếu khách là khách {{ brand.company }} (mã căn, dự án, ...).",
                    },
                },
                "required": [],
            },
        },
    },
    "kb_search": {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": (
                "Tra cứu NỘI DUNG chi tiết về dự án trong tài liệu: điều khoản trong chính sách bán hàng (chiết "
                "khấu, khuyến mãi, vay vốn, tiến độ thanh toán), tiện ích, vị trí chi tiết, thiết kế, vật liệu, pháp "
                "lý, hoặc so sánh giữa các dự án.[TOOL:search_units] KHÔNG dùng để hỏi GIÁ CĂN / khoảng giá / còn căn "
                "nào — tài liệu không có giá, giá thật nằm ở kho căn: search_units (find_project trước nếu khách nêu "
                "tên một dự án).[/TOOL:search_units]"
                "[TOOL:get_document] Khách hỏi/xin BẢN chính sách bán hàng ('có CSBH nào đang áp dụng', 'CSBH mới "
                "nhất', 'cho xin chính sách bán hàng') → find_project rồi get_document (danh sách bản + link), KHÔNG "
                "kb_search.[/TOOL:get_document] GỌI THẲNG ngay lượt "
                "đầu, KHÔNG gọi find_project trước ('pháp lý Noble Crystal thế nào' → kb_search(query='pháp lý "
                "Noble Crystal') luôn) — đưa nguyên tên dự án khách nói vào query là đủ "
                "khoanh vùng; project_filter chỉ điền khi ĐÃ có mã sẵn, so sánh nhiều dự án → BỎ TRỐNG "
                "project_filter. Ví dụ 'dự án đó có bể bơi không', 'pháp lý dự án thế nào'. Link tour 360 KHÔNG đi "
                "đường này (send_media content_type=tour_360). QUAN TRỌNG: đây là tìm kiếm ngữ nghĩa, KHÔNG phải "
                "hỏi-đáp — đừng chép nguyên văn câu khách vào query, hãy DIỄN GIẢI LẠI thành truy vấn rõ chủ đề, giàu "
                "từ khóa bất động sản, tự đủ nghĩa (thay 'nó / đó / dự án này' bằng tên thật), bỏ lời dẫn và từ đệm."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Truy vấn tìm kiếm tiếng Việt đã ĐƯỢC DIỄN GIẢI LẠI, không phải câu nói "
                            "thô của khách. Viết như một cụm tìm kiếm tài liệu: nêu rõ chủ đề + từ "
                            "khóa cốt lõi, tự đủ nghĩa, không dùng đại từ mơ hồ. "
                            "Ví dụ: khách nói 'thế còn cái kia thì sao, có chỗ cho trẻ con chơi "
                            "không' → query 'tiện ích khu vui chơi trẻ em dự án Noble Crystal'. "
                            "Khách nói 'giấy tờ ổn không' → query 'tình trạng pháp lý sổ đỏ dự án'."
                        ),
                    },
                    "project_filter": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về, để lọc kết quả về đúng dự án. "
                            "Bỏ trống để tìm tất cả / dùng dự án đang quan tâm."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    "discover_projects": {
        "type": "function",
        "function": {
            "name": "discover_projects",
            "description": (
                "Tool DỰ ÁN hai chế độ. (1) KHÁM PHÁ (bỏ trống project_code): khách chưa biết chọn dự án nào — 'bên "
                "em có dự án gì', 'dự án ở khu X', 'dự án của chủ đầu tư Y', 'đang mở bán gì'. Trả về MỘT TRANG dự "
                "án nổi bật + tổng số khớp + gợi ý tiêu chí thu hẹp: giới thiệu tối đa 3 dự án/lượt rồi hỏi thêm "
                "tiêu chí (theo suggested_narrow) hoặc mời nghe thêm — KHÔNG đọc quá 3 tên/lượt. Khách muốn xem thêm "
                "→ gọi lại CÙNG tham số với index=next_index; khách cho thêm tiêu chí → gọi lại tiêu chí mới với "
                "index=0. Kết quả RỖNG mà lượt gọi có sale_phase / budget_max / product_type → gọi lại NGAY bỏ tiêu "
                "chí hẹp nhất rồi mới trả lời, không hỏi khách trước. (2) CHI TIẾT một dự án (truyền project_code — "
                "mã từ find_project hoặc dự án đang quan tâm trong hồ sơ): khách hỏi giới thiệu / tổng quan một dự "
                "án cụ thể ('dự án Noble Crystal thế nào', 'giới thiệu cho em dự án đó') → trả tổng quan đầy đủ "
                "(vị trí, quy mô, tiện ích, hình thức sở hữu, giai đoạn bán); các tiêu chí lọc bị bỏ qua. Khác "
                "search_units (căn cụ thể trong kho căn)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string",
                        "description": (
                            "CHỈ truyền khi khách hỏi CHI TIẾT một dự án: mã canonical do find_project trả "
                            "về, hoặc mã 'Dự án quan tâm' trong hồ sơ khi khách nói 'dự án này / đó'. "
                            "Bỏ trống = chế độ khám phá danh sách."
                        ),
                    },
                    "region": {
                        "type": "string",
                        "description": (
                            "Khu vực lấy đúng lời khách — nhận cả cấp thành phố/quận/phường/tên đường "
                            "(khớp trên cả khu vực lẫn địa chỉ dự án); '' = không lọc khu vực."
                        ),
                    },
                    "budget_max": {
                        "type": "number",
                        "description": (
                            "Ngân sách tối đa, VNĐ THỰC — khách nói '20 tỷ' → 20000000000, "
                            "'800 triệu' → 800000000. KHÔNG truyền số tắt kiểu 20. Tùy chọn."
                        ),
                    },
                    "product_type": {
                        "type": "string",
                        "enum": ["chung_cu", "biet_thu", "lien_ke", "shophouse", "dat_nen", "van_phong"],
                        "description": "Loại hình sản phẩm khách muốn. Tùy chọn.",
                    },
                    "purpose": {
                        "type": "string",
                        "enum": ["live", "invest"],
                        "description": "Mục đích ở/đầu tư (chỉ để tư vấn, KHÔNG lọc). Tùy chọn.",
                    },
                    "investor": {"type": "string", "description": "Tên chủ đầu tư khách hỏi. Tùy chọn."},
                    "sale_phase": {
                        "type": "string",
                        "enum": ["sap_mo_ban", "dang_ban", "ban_giao", "dong_gio_hang"],
                        "description": "Giai đoạn bán của dự án. Tùy chọn.",
                    },
                    "index": {
                        "type": "integer",
                        "description": "Offset phân trang, mặc định 0. Xem thêm → truyền next_index của lần trước.",
                    },
                },
                "required": [],
            },
        },
    },
    "get_document": {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": (
                "Lấy BẢN tài liệu của dự án — CSBH / pháp lý / brochure (trả danh sách bản: tiêu đề, nội dung tóm "
                "tắt, link file). Gọi khi khách xin file HOẶC hỏi có bản chính sách bán hàng nào đang áp dụng / bản "
                "mới nhất ('cho xin CSBH mới nhất của X' → find_project rồi get_document). Trả lời bằng tên bản + "
                "ngày hiệu lực ghi trong tiêu đề, bản mới nhất trước; không có link thì nói rõ chỉ có tên. Chi tiết "
                "điều khoản bên trong (chiết khấu, vay, tiến độ) → kb_search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về; bỏ trống để dùng dự án đang quan tâm."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Từ khóa loại tài liệu khách cần (VD 'CSBH', 'pháp lý'). Tùy chọn.",
                    },
                },
                "required": [],
            },
        },
    },
    "search_units": {
        "type": "function",
        "function": {
            "name": "search_units",
            "description": (
                "Tìm và gợi ý CĂN cụ thể trong kho căn — tool DUY NHẤT cho câu hỏi về căn: còn căn nào, giá căn, "
                "hướng / tầng / diện tích / số phòng ngủ, 'có X tỷ mua căn nào', 'nên xem căn nào'. Hỏi GIÁ ('căn 2 "
                "phòng ngủ giá khoảng bao nhiêu', 'biệt thự X tầm bao nhiêu một căn') cũng đi tool này — giá thật ở "
                "kho căn, KHÔNG ở tài liệu kb_search: trả lời bằng khoảng giá + số căn còn trong kết quả. scope BẮT "
                "BUỘC: 'in_project' khi khách hỏi căn trong MỘT dự án cụ thể ('còn căn 3 phòng ngủ dưới 5 tỷ không', "
                "'có căn nào hướng Đông Nam', 'căn tầm 120m' về dự án đã chốt / đang nói tới — bỏ trống project_code "
                "hệ thống tự dùng dự án đang quan tâm; chưa rõ dự án nào thì find_project trước); 'all_projects' khi "
                "khách CHƯA chốt dự án, muốn tư vấn chung theo ngân sách / khu vực / số phòng ngủ ('có 20 tỷ mua căn "
                "nào', 'tầm 4 tỷ ở Tây Hồ nên xem căn nào') — GỌI NGAY với tiêu chí đã biết, thiếu tiêu chí KHÔNG "
                "hỏi thêm trước khi gọi. Kết quả có HAI nhóm: `units` (đúng ngân sách, căn sát ngân sách xếp lên "
                "đầu) và `upsell_units` (nhỉnh hơn ngân sách trong biên, kèm price_delta_pct/highlights) — giới "
                "thiệu theo ĐÚNG thứ tự trả về, KHÔNG tự lọc lại theo hướng rẻ hơn. Làm theo `instruction` và "
                "`upsell_instruction` trong kết quả ngay tại lượt này, KHÔNG bỏ qua, KHÔNG hỏi xin phép trước khi "
                "giới thiệu. Kết quả trả theo TRANG 6 căn (`counts.total`/`has_more`/`next_index`): khách chê các "
                "căn vừa xem / hỏi 'còn căn nào khác không' với CÙNG tiêu chí → gọi lại với index=next_index lấy "
                "các căn KẾ TIẾP, đừng lặp lại căn khách đã chê; khách ĐỔI tiêu chí thì về index=0. Kết quả có "
                "note=no_units_in_area_band → không có căn đúng tầm diện tích, đây là các căn gần nhất: nói rõ diện "
                "tích thật và mức chênh rồi hỏi khách có muốn xem không. "
                "[FENG_SHUI]Phong thủy: khách hỏi theo tuổi / mệnh / năm sinh ('tuổi Tị hợp căn nào', 'mệnh Mộc', "
                "'sinh 1990 hợp hướng nào') → truyền birth_year (năm DƯƠNG LỊCH) + gender nếu biết; hoặc menh khi "
                "khách khai thẳng; hoặc zodiac khi khách chỉ nói tuổi (chỉ có con giáp mà chưa có năm sinh → tool "
                "nhắc hỏi năm sinh, hỏi tối đa 2 lần; giờ sinh không cần). KHÔNG tự bịa hướng / mệnh — hệ thống tính "
                "bằng code. Tool báo không có căn hợp hướng → nói thật, gợi ý căn hợp ngân sách, mời chuyển chuyên "
                "viên nếu khách muốn tư vấn sâu.[/FENG_SHUI]"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["in_project", "all_projects"],
                        "description": (
                            "in_project: căn trong MỘT dự án (đã chốt / đang quan tâm). "
                            "all_projects: gợi ý xuyên tất cả dự án khi khách chưa chốt dự án."
                        ),
                    },
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về. scope=in_project: bỏ trống để dùng "
                            "dự án đang quan tâm. scope=all_projects: bỏ trống (mặc định); truyền mã chỉ khi "
                            "muốn bó gợi ý trong một dự án."
                        ),
                    },
                    "product_type": {
                        "type": "string",
                        "enum": [
                            "chung_cu",
                            "studio",
                            "duplex",
                            "penthouse",
                            "officetel",
                            "condotel",
                            "biet_thu",
                            "lien_ke",
                            "shophouse",
                            "nha_pho",
                            "dat_nen",
                            "van_phong",
                        ],
                        "description": "Loại hình sản phẩm căn. Tùy chọn.",
                    },
                    "max_price": {
                        "type": "number",
                        "description": (
                            "Giá tối đa / ngân sách của khách, VNĐ THỰC — khách nói '5 tỷ' → 5000000000, "
                            "'800 triệu' → 800000000. KHÔNG truyền số tắt kiểu 5. Lọc cứng (đã nới biên "
                            "chèo kéo tự động). Tùy chọn."
                        ),
                    },
                    "bedrooms": {"type": "integer", "description": "Số phòng ngủ mong muốn. Tùy chọn."},
                    "region": {
                        "type": "string",
                        "description": (
                            "Khu vực khách muốn (đúng lời khách) — nhận cả cấp thành phố/quận/phường/tên đường. "
                            "CHỈ dùng với scope=all_projects; trong một dự án đã chốt thì bỏ trống."
                        ),
                    },
                    "purpose": {"type": "string", "description": "Mục đích ở/đầu tư (chỉ để tư vấn, KHÔNG lọc)."},
                    "area_m2": {
                        "type": "number",
                        "description": (
                            "Diện tích khách MONG MUỐN (m²) khi khách nói 'tầm / khoảng / cỡ X m' → truyền "
                            "đúng X; hệ thống tự lấy dải quanh X và xếp căn gần X nhất lên đầu. TUYỆT ĐỐI "
                            "KHÔNG dịch 'tầm X' thành min_area (lọc cứng ≥X bỏ mất căn hơi nhỏ hơn X)."
                        ),
                    },
                    "min_area": {
                        "type": "number",
                        "description": (
                            "Diện tích thông thủy tối thiểu (m²) — CHỈ khi khách nói rõ 'từ X trở lên / trên X'. "
                            "Tùy chọn."
                        ),
                    },
                    "max_area": {
                        "type": "number",
                        "description": (
                            "Diện tích thông thủy tối đa (m²) — CHỈ khi khách nói rõ 'dưới X / không quá X'. Tùy chọn."
                        ),
                    },
                    "direction": {
                        "type": "string",
                        "enum": [
                            "dong",
                            "tay",
                            "nam",
                            "bac",
                            "dong_bac",
                            "dong_nam",
                            "tay_bac",
                            "tay_nam",
                        ],
                        "description": "Hướng căn/ban công khách YÊU CẦU RÕ (lọc cứng). Tùy chọn.",
                    },
                    "floor": {"type": "integer", "description": "Tầng mong muốn (VD 12). Tùy chọn."},
                    "block": {"type": "string", "description": "Tòa/block trong dự án (VD 'A', 'T1'). Tùy chọn."},
                    "unit_code": {
                        "type": "string",
                        "description": "Mã căn hộ cụ thể nếu khách nêu (VD 'A-1203'). Tùy chọn.",
                    },
                    "sale_status": {
                        "type": "string",
                        "enum": ["available", "booked", "sold"],
                        "description": (
                            "Lọc theo tình trạng căn: available (còn bán), booked (đã giữ chỗ), "
                            "sold (đã bán). Mặc định 'available'. Tùy chọn."
                        ),
                    },
                    "index": {
                        "type": "integer",
                        "description": (
                            "Vị trí bắt đầu trang (số căn đã xem). Bỏ trống/0 = trang đầu. Khách muốn xem "
                            "CĂN KHÁC cùng tiêu chí → truyền next_index của kết quả trước. Đổi tiêu chí → 0."
                        ),
                    },
                    "birth_year": {
                        "type": "integer",
                        "description": "Năm sinh DƯƠNG LỊCH (yyyy, vd 1990). Chỉ truyền khi khách quan tâm phong thủy.",
                    },
                    "gender": {
                        "type": "string",
                        "enum": ["M", "F"],
                        "description": "Giới tính để tính cung phi bát trạch. Bỏ trống → lấy từ hồ sơ.",
                    },
                    "menh": {
                        "type": "string",
                        "enum": ["kim", "moc", "thuy", "hoa", "tho"],
                        "description": "Ngũ hành bản mệnh khi khách khai thẳng ('anh mệnh Mộc').",
                    },
                    "zodiac": {
                        "type": "string",
                        "enum": ["ty", "suu", "dan", "mao", "thin", "ti", "ngo", "mui", "than", "dau", "tuat", "hoi"],
                        "description": (
                            "Con giáp khi khách chỉ nói tuổi ('tuổi Tị'). Ưu tiên hỏi năm sinh để chính xác."
                        ),
                    },
                },
                "required": ["scope"],
            },
        },
    },
    "analyze_projects": {
        "type": "function",
        "function": {
            "name": "analyze_projects",
            "description": (
                "Thống kê / so sánh / xếp hạng / đếm / min-max-trung bình trên TOÀN BỘ dự án và quỹ căn "
                "bằng MỘT câu SQL SELECT (PostgreSQL). Dùng cho câu hỏi TỔNG QUÁT cần gộp dữ liệu nhiều dự án "
                "('dự án nào nhiều loại hình nhất', 'giá trung bình từng dự án', 'khu nào còn nhiều căn 2 ngủ "
                "nhất') VÀ câu TỒN KHO của một dự án ('dự án X còn bao nhiêu căn', 'còn loại nào', 'hướng nào "
                "còn' — GROUP BY trên agent_units_v). "
                "KHÔNG dùng cho: nội dung tài liệu/chính sách/pháp lý (kb_search), tìm/gợi ý căn theo nhu cầu "
                "khách (search_units).\n"
                "CHỈ được SELECT từ 2 view:\n"
                "- tenant_data.agent_projects_v(project_code, name, region, address, investor, developer, "
                "category, sale_phase, ownership_form, total_land_area_m2)\n"
                "- tenant_data.agent_units_v(project_code, project_name, zone_code, unit_code, product_type, "
                "bedrooms, block, floor, direction, area_built_m2, area_land_m2, price_vnd, price_per_m2_vnd, "
                "sale_status)\n"
                "Quy ước: price_vnd đơn vị VND, 0/NULL nghĩa là CHƯA CÓ GIÁ → mọi phép tính giá phải kèm "
                "FILTER (WHERE price_vnd > 0) hoặc WHERE price_vnd > 0; category là MẢNG text → lọc bằng "
                "'giá trị' = ANY(category); so khớp chữ dùng ILIKE '%...%'. Luôn kèm LIMIT (tối đa 50).\n"
                "Ví dụ 1 — 'dự án nào có nhiều loại hình nhất': SELECT project_code, project_name, "
                "COUNT(DISTINCT product_type) AS so_loai_hinh FROM tenant_data.agent_units_v "
                "GROUP BY 1,2 ORDER BY so_loai_hinh DESC LIMIT 3\n"
                "Ví dụ 2 — 'giá trung bình căn hộ từng dự án': SELECT project_code, project_name, "
                "ROUND(AVG(price_vnd) FILTER (WHERE price_vnd > 0)) AS gia_tb "
                "FROM tenant_data.agent_units_v WHERE product_type ILIKE '%căn hộ%' "
                "GROUP BY 1,2 ORDER BY gia_tb LIMIT 10\n"
                "Ví dụ 3 — tồn kho 'dự án X còn những loại căn nào, giá từ bao nhiêu': SELECT product_type, "
                "COUNT(*) AS so_can, MIN(price_vnd) FILTER (WHERE price_vnd > 0) AS gia_tu "
                "FROM tenant_data.agent_units_v WHERE project_code = '<mã find_project>' "
                "AND sale_status = 'available' GROUP BY 1 ORDER BY so_can DESC LIMIT 10\n"
                "Kết quả rỗng → nới điều kiện lọc rồi thử lại, KHÔNG escalate. Chỉ nói số liệu CÓ TRONG kết quả, "
                "không làm tròn quá đà khi khách hỏi con số cụ thể. Tool báo lỗi SQL → sửa câu SQL theo thông báo rồi "
                "gọi lại (tối đa 1 lần sửa), vẫn lỗi → trả lời bằng discover_projects / kb_search.\n"
                "[VOCAB]"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "MỘT câu SELECT PostgreSQL trên 2 view trên. Không DML/DDL/bảng khác — "
                            "hệ thống chặn ở tầng DB."
                        ),
                    }
                },
                "required": ["sql"],
            },
        },
    },
    "find_project": {
        "type": "function",
        "function": {
            "name": "find_project",
            "description": (
                "Xác định MÃ dự án từ tên khách nói TRƯỚC khi dùng tool cần mã chính xác (discover_projects chế độ "
                "chi tiết dự án / get_document / search_units trong một dự án / booking / send_media). KHÔNG cần "
                "cho kb_search — "
                "kb_search đi thẳng với tên dự án trong query. KHÔNG gọi khi khách chỉ nói 'dự án này / đó' hoặc "
                "không nhắc tên dự án mới mà hồ sơ đã có 'Dự án quan tâm' — các tool kia tự dùng dự án đó khi bỏ "
                "trống project_code. Truyền region_hint / investor_hint nếu khách đã nhắc. Xử lý kết quả: 'resolved' "
                "→ dùng mã đó cho các tool sau (hệ thống tự nhớ dự án đang quan tâm, không cần truyền lại). "
                "'ambiguous' → nếu tên khách nói đã CHỈ RÕ đúng một ứng viên (khách nói kèm từ / số phân biệt, vd "
                "'Ocean Park 2' khớp '...OCEAN PARK 2') → tự chọn mã đó, KHÔNG hỏi lại; chỉ đọc danh sách ứng viên và "
                "hỏi khách chọn (theo khu vực) khi thực sự chưa rõ. 'not_found' → xin khách nhắc lại tên hoặc khu "
                "vực, nhưng hỏi mở kiểu này TỐI ĐA 1 lần; giọng nói hay bị nghe méo tên dự án, nên nếu kết quả kèm "
                "best_guess hoặc khách đã nhắc lại một lần → ĐỪNG hỏi mở thêm: chọn ứng viên khả dĩ nhất và hỏi xác "
                "nhận CÓ/KHÔNG (đọc tên đầy đủ), theo thứ tự (a) dự án trong recently_listed (danh sách vừa giới "
                "thiệu cho khách) mà tên khách nói nghe gần giống nhất — kể cả tên tiếng Anh đọc kiểu Việt ('san sai' "
                "≈ Sunshine, 'vin hôm' ≈ Vinhomes); (b) best_guess; (c) candidates của lượt ambiguous gần nhất. Khách "
                "xác nhận 'đúng' → gọi lại find_project(query=<tên đầy đủ>) để hệ thống ghi nhớ rồi dùng mã đó; khách "
                "phủ nhận → hỏi ứng viên kế tiếp hoặc xin thêm khu vực. Tuyệt đối không bịa mã ngoài danh sách trả "
                "về, không thay bằng mã của dự án khác. Ví dụ query='Noble Crystal Tây Hồ'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Tên dự án khách nói (nguyên văn, kể cả sai chính tả)."},
                    "region_hint": {"type": "string", "description": "Khu vực/quận khách đã nhắc, nếu có."},
                    "investor_hint": {"type": "string", "description": "Chủ đầu tư/thương hiệu khách đã nhắc, nếu có."},
                },
                "required": ["query"],
            },
        },
    },
    "booking": {
        "type": "function",
        "function": {
            "name": "booking",
            "description": (
                "Đặt / đổi / xem lịch tham quan dự án. Làm ĐÚNG thứ tự, KHÔNG gộp bước. Bước 0 — dự án: lấy từ hồ sơ "
                "(dự án đang quan tâm) hoặc gọi find_project với tên khách nói; find_project trả not_found → DỪNG "
                "flow ngay: báo bên em hiện không có dự án đó, xin khách nhắc lại tên / khu vực, KHÔNG hỏi ngày giờ, "
                "KHÔNG gọi booking với mã dự án khác. Bước 1 — action='check_availability' NGAY khi khách muốn đặt "
                "lịch, kèm preferred_date chỉ khi khách nêu ngày cụ thể; khách nói mơ hồ ('cuối tuần', 'tuần sau') → "
                "vẫn gọi không kèm ngày rồi đọc các ngày / khung giờ trống ra để khách chọn — KHÔNG hỏi ngày trước "
                "khi gọi; bước này CHƯA hỏi tên / số. Bước 2 — CHỈ sau khi khách đã chốt ngày và giờ, hỏi RIÊNG tên "
                "và số đặt lịch (không gộp vào câu hỏi ngày giờ, không suy ra 'đồng ý' từ việc khách chọn giờ): tên — "
                "'Mình đặt lịch dưới tên [tên trong hồ sơ] phải không?' → đồng ý: use_profile_name=true, khách đọc "
                "tên khác (kể cả đặt hộ): name=...; số — 'dùng số đang gọi để đặt lịch không?' → đồng ý: "
                "use_calling_phone=true, khách đọc số khác: phone=... Tên / số đặt lịch là thông tin CỦA LỊCH HẸN, "
                "KHÔNG gọi update_customer để lưu. Bước 3 — action='schedule', confirmed=true, kèm tên + số đã xác "
                "nhận. Còn thiếu → tool trả thông báo nhắc, hỏi khách đúng theo thông báo đó; sau 2 lần khách vẫn "
                "không cung cấp, tool tự chốt. action='list' xem lịch đã đặt; action='modify' + booking_id + CHỈ "
                "field cần đổi (new_preferred_date / new_preferred_time / name / phone) — field không truyền giữ "
                "nguyên, KHÔNG hỏi lại điều không đổi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check_availability", "schedule", "list", "modify"],
                    },
                    "preferred_date": {
                        "type": "string",
                        "description": ("Ngày mong muốn DD/MM/YYYY (check_availability để lọc, schedule bắt buộc)."),
                    },
                    "preferred_time": {
                        "type": "string",
                        "description": "Khung giờ khách chọn, ví dụ '09:00 - 10:00' (schedule).",
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Tên người đặt lịch khi khách ĐỌC một tên (schedule) — kể cả đặt hộ "
                            "người khác. Bỏ trống nếu khách dùng tên trong hồ sơ (khi đó đặt "
                            "use_profile_name=true). KHÔNG dùng để cập nhật hồ sơ khách."
                        ),
                    },
                    "use_profile_name": {
                        "type": "boolean",
                        "description": ("True khi khách xác nhận dùng tên trong hồ sơ để đặt lịch (schedule)."),
                    },
                    "phone": {
                        "type": "string",
                        "description": (
                            "SĐT đặt lịch khi khách ĐỌC một số khác số đang gọi (schedule). "
                            "Bỏ trống nếu khách dùng số đang gọi (khi đó đặt use_calling_phone=true)."
                        ),
                    },
                    "use_calling_phone": {
                        "type": "boolean",
                        "description": ("True khi khách xác nhận dùng chính số đang gọi để đặt lịch (schedule)."),
                    },
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về; bỏ trống để dùng dự "
                            "án đang quan tâm. find_project trả not_found → KHÔNG gọi booking, "
                            "TUYỆT ĐỐI không truyền mã của dự án khác thay thế — báo khách bên "
                            "em hiện không có dự án đó."
                        ),
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "True khi khách đã chốt ngày và giờ (schedule).",
                    },
                    "notes": {"type": "string", "description": "Ghi chú thêm cho lịch (schedule)."},
                    "booking_id": {"type": "string", "description": "Mã lịch APT... cần đổi (modify)."},
                    "new_preferred_date": {"type": "string", "description": "Ngày mới DD/MM/YYYY (modify)."},
                    "new_preferred_time": {
                        "type": "string",
                        "description": "Giờ mới, ví dụ '09:00 - 10:00' (modify).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    "no_lookup_needed": {
        "type": "function",
        "function": {
            "name": "no_lookup_needed",
            "description": (
                "Van xả khi hệ thống yêu cầu lượt này phải gọi tool nhưng câu của khách "
                "là xã giao / không cần tra dữ liệu (chào hỏi, cảm ơn, xác nhận ngắn, small talk). "
                "Gọi tool này rồi trả lời khách tự nhiên. KHÔNG dùng khi khách hỏi về dự án / "
                "căn hộ / giá / lịch — những câu đó phải gọi tool dữ liệu tương ứng."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "escalate": {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": (
                "Chuyển cuộc gọi sang chuyên viên là người thật — cách duy nhất đưa cuộc gọi ra khỏi luồng tự động. "
                "Dùng khi câu hỏi chạm HỢP ĐỒNG / pháp lý giao dịch của khách — kể cả khách CHƯA mua: điều khoản / "
                "ràng buộc / điểm bất "
                "lợi trong hợp đồng mua bán; chuyển nhượng, bán lại, sang tên (chưa có sổ, trước bàn giao) và phí / "
                "thuế đi kèm; cam kết lợi nhuận hay bảo lãnh 'có ghi vào hợp đồng không'; thanh toán / bảo hành / sổ "
                "hồng của căn đã mua; khách đòi mức giá riêng NGOÀI chính sách; khách yêu cầu gặp người thật hoặc hỏi "
                "'em là người hay máy?' (→ escalate ngay, KHÔNG hỏi lại lý do); khiếu nại nghiêm trọng. Những câu "
                "này → escalate NGAY, KHÔNG kb_search trước, KHÔNG tự nêu con số. Chiết khấu / ưu đãi theo CSBH (thanh "
                "toán sớm, đóng một lần, voucher), đặt cọc giữ chỗ bao nhiêu, tiến độ thanh toán là NỘI DUNG tài liệu "
                "→ kb_search, không phải đòi giá riêng. Đặt / đổi / hủy lịch xem nhà → booking, KHÔNG escalate. Pháp "
                "lý của "
                "DỰ ÁN (sổ hồng lâu dài hay 50 năm, giấy phép, tiến độ, 'pháp lý có vấn đề không') KHÔNG phải lý do "
                "escalate → kb_search. Gọi NGAY "
                "trong lượt, KHÔNG tự soạn lời hứa liên hệ trước khi gọi — chờ tool trả về rồi truyền đạt đúng field "
                "'message' (đổi theo giờ làm việc). department: chọn theo mục 'Đầu mối chuyển tiếp'; bỏ trống → hệ "
                "thống dùng bộ phận tiếp nhận mặc định. Kết quả rỗng của tool tra cứu KHÔNG phải lý do escalate; tool "
                "trả đúng câu 'Thông tin đã được chuyển đến chuyên viên tư vấn' = hệ thống ĐÃ tự chuyển → chỉ báo "
                "khách, KHÔNG gọi lại."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["check_state", "transfer"]},
                    "reason": {"type": "string"},
                    "department": {
                        "type": "string",
                        "description": (
                            "Bộ phận tiếp nhận (theo mục 'Đầu mối chuyển tiếp'); bỏ trống = mặc định tenant."
                        ),
                    },
                    "priority": {"type": "string", "enum": ["normal", "high", "urgent"]},
                },
                "required": ["action"],
            },
        },
    },
    "send_media": {
        "type": "function",
        "function": {
            "name": "send_media",
            "description": (
                "Gửi hình ảnh / video / tour 360 của dự án cho khách qua ứng dụng {{ brand.app_name }} (mặt bằng, "
                "phối cảnh, tiện ích, vị trí — những gì khó tả bằng lời); hiện ngay trong app. Ba trường hợp gọi: (1) "
                "CHỦ ĐỘNG khi giới thiệu / tổng quan MỘT dự án cụ thể ('giới thiệu dự án X', 'X thế nào', hoặc ngay "
                "sau khi tra tổng quan) → category=tong_quan, KHÔNG chờ khách xin; ảnh tổng quan mỗi dự án chỉ gửi "
                "MỘT lần, khách xin video sau đó vẫn gửi bình thường. (2) PHẢN HỒI khi khách hỏi nội dung trực quan "
                "(ảnh, mặt bằng, vị trí, tiện ích, nội / ngoại thất, tiến độ) → category đúng loại khách hỏi. (3) "
                "Khách xin VIDEO ('cho xem video', 'có clip không', 'quay dự án') → content_type=video và BỎ TRỐNG "
                "category (video nằm rải rác ở nhiều category; tong_quan theo quán tính sẽ KHÔNG ra video), trừ khi "
                "khách nói rõ loại ('video tiến độ' → thêm category=tien_do). Tour 360 / tham quan ảo / VR / 'xem "
                "360' → content_type=tour_360 — ĐÂY là đường gửi tour, KHÔNG dùng kb_search, KHÔNG chép link vào câu "
                "trả lời. Phải truyền ÍT NHẤT MỘT trong category / content_type. Gọi ÂM THẦM: TUYỆT ĐỐI KHÔNG nói câu "
                "thông báo / filler nào về việc gửi ('em gửi qua app', 'chờ em một chút') — cứ tiếp tục tư vấn; sau "
                "đó chỉ nói ảnh là gì theo caption. KHÔNG gửi khi chỉ liệt kê NHIỀU dự án — chỉ khi đang tập trung "
                "vào một dự án. Tool trả error / retry (thiếu cả category lẫn content_type, giá trị sai, thiếu dự án) "
                "→ gọi lại đúng tham số theo message. Tool trả note=category_fallback: ảnh CHƯA gửi, candidates là "
                "ảnh gần nhất tìm được — đọc caption, chọn cái phù hợp rồi gọi lại với ids=[ref] và nói rõ đây không "
                "phải ảnh khách xin ('chưa có ảnh nội thất, em gửi ảnh bể bơi nhé') — ngoại lệ duy nhất của luật âm "
                "thầm; không có cái nào phù hợp → nói thẳng MỘT câu là chưa có, KHÔNG nối thêm 'hoặc' đưa hai lựa "
                "chọn khác cho khách chọn. Mọi trường hợp khác: mặc định là GỬI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Câu hỏi/yêu cầu nguyên văn của khách (tiếng Việt).",
                    },
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "CHỈ dùng ở lượt gửi của luồng hai bước. Khi workspace không có "
                            "ảnh đúng category, tool trả về `candidates` kèm `ref` thay vì gửi "
                            "ảnh — đọc caption, chọn cái phù hợp, rồi gọi lại send_media với "
                            "ids là những ref đó. Lượt đầu KHÔNG truyền trường này."
                        ),
                    },
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về; bỏ trống để dùng dự án đang quan tâm."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": list(SEND_MEDIA_CATEGORIES),
                        "description": (
                            "Loại media: tong_quan (tổng quan), ngoai_that (ngoại thất), "
                            "noi_that (nội thất), tien_ich (tiện ích), mat_bang (mặt bằng), "
                            "vi_tri (vị trí), tien_do (tiến độ). "
                            "Chủ động giới thiệu tổng quan dự án → dùng tong_quan. "
                            "Khách xin video chung mà không nói rõ loại → BỎ TRỐNG."
                        ),
                    },
                    "content_type": {
                        "type": "string",
                        "enum": list(SEND_MEDIA_CONTENT_TYPES),
                        "description": (
                            "video khi khách xin video/clip/quay dự án; image khi khách xin ảnh/hình; "
                            "tour_360 khi khách xin tour/tham quan ảo/VR/xem 360. Bỏ trống = mọi loại."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
}


_BRAND_DEFAULTS = {"company": "Noble", "app_name": "NobleX"}


def _render_brand(text: str, brand: dict) -> str:
    if "{{" not in text:
        return text
    return text.replace("{{ brand.company }}", brand.get("company", _BRAND_DEFAULTS["company"])).replace(
        "{{ brand.app_name }}", brand.get("app_name", _BRAND_DEFAULTS["app_name"])
    )


def schemas_for(names: list[str], codes: list[str] | None = None) -> list[dict]:
    """Return tool schemas for the given names (order preserved, unknown skipped).

    ``codes`` is accepted for backward compatibility but ignored — project codes
    are no longer enumerated into schemas; the LLM obtains a code via the
    find_project tool and passes it as a free-text string.
    """
    return [SCHEMAS[name] for name in names if name in SCHEMAS]


_FENG_SHUI_PARAMS = ("birth_year", "gender", "menh", "zodiac")
# Đoạn hướng dẫn phong thủy trong description search_units (tool căn hợp nhất) —
# cắt cùng lúc với các tham số khi tenant không bật ranker feng_shui
# (persona_compose cắt vùng FENG_SHUI trong RULES theo cùng cờ).
_FENG_SHUI_SPAN = _re.compile(r"\s*\[FENG_SHUI\].*?\[/FENG_SHUI\]", _re.DOTALL)
# Câu trong description nhắc tới tool KHÁC: chỉ giữ khi tool đó cũng được offer.
_TOOL_SPAN = _re.compile(r"\[TOOL:(\w+)\](.*?)\[/TOOL:\1\]", _re.DOTALL)


def build_schemas(names: list[str], *, brand: dict | None = None, rankers: frozenset | None = None) -> list[dict]:
    """Tool schemas for ``names``. Deep-copies so the shared module-level
    ``SCHEMAS`` is never mutated. ``schemas_for`` stays copy-free for callers
    that want the raw static schema."""
    from noble_agent.agent.tools import registry
    from noble_agent.tenant.loader import get_tenant_context

    try:
        _tenant_id = get_tenant_context().tenant_id
    except Exception:
        _tenant_id = "noble"

    # Static built-ins come from SCHEMAS; a name NOT in SCHEMAS is a custom
    # tenant tool — pull its schema off the registered ToolSpec so it is
    # actually OFFERED to the LLM (not just dispatchable). Order follows `names`.
    out: list[dict] = []
    for name in names:
        if name in SCHEMAS:
            out.append(_copy.deepcopy(SCHEMAS[name]))
            continue
        spec = registry.resolve(_tenant_id, name)
        if spec is not None and spec.schema:
            out.append(_copy.deepcopy(spec.schema))

    # 2) Gate the feng-shui overlay params behind rankers (override or manifest).
    if rankers is None:
        try:
            rankers = get_tenant_context().rankers
        except Exception:
            rankers = frozenset({"feng_shui"})  # default: Noble behaviour
    for schema in out:
        if schema["function"]["name"] != "search_units":
            continue
        fn = schema["function"]
        if "feng_shui" in rankers:
            # Giữ hướng dẫn phong thủy, chỉ bỏ hai token đánh dấu.
            fn["description"] = fn["description"].replace("[FENG_SHUI]", "").replace("[/FENG_SHUI]", "")
        else:
            fn["description"] = _FENG_SHUI_SPAN.sub("", fn["description"]).rstrip()
            props = fn["parameters"].get("properties", {})
            for p in _FENG_SHUI_PARAMS:
                props.pop(p, None)

    # 2b) [TOOL:x]…[/TOOL:x] — tenant không bật x thì không được bảo LLM gọi x.
    enabled = set(names)
    for schema in out:
        fn = schema["function"]
        if "description" in fn:
            fn["description"] = _TOOL_SPAN.sub(
                lambda m: m.group(2) if m.group(1) in enabled else "", fn["description"]
            ).rstrip()

    # 3) Render brand tokens LAST so it also covers injected custom-param
    #    descriptions (Phase 3d). A residual ``{{`` after rendering means an
    #    unhandled token slipped through — log it (fail-loud) instead of
    #    shipping a raw template to the LLM.
    if brand is None:
        try:
            brand = dict(get_tenant_context().brand)
        except Exception:
            brand = dict(_BRAND_DEFAULTS)
    for schema in out:
        fn = schema["function"]
        if "description" in fn:
            fn["description"] = _render_brand(fn["description"], brand)
        for prop in fn.get("parameters", {}).get("properties", {}).values():
            if isinstance(prop, dict) and "description" in prop:
                prop["description"] = _render_brand(prop["description"], brand)
        if "{{" in fn.get("description", "") or any(
            "{{" in p.get("description", "")
            for p in fn.get("parameters", {}).get("properties", {}).values()
            if isinstance(p, dict)
        ):
            logger.warning("build_schemas: unrendered template token left in %s schema", fn.get("name"))
    return out
