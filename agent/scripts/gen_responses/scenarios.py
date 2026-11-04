"""
Scenario definitions for NobleX voice agent response generation.

Each scenario represents a specific agent + skill + intent combination
with pre-computed tool outputs (from mock services) and customer context.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str                           # File name prefix, e.g. "01_greeting"
    agent: str                        # "router" | "consultant" | "support"
    skill: str                        # Skill name
    intent: str                       # Intent code
    category: str                     # Output folder, e.g. "01_router"
    customer_query: str               # Simulated customer utterance
    tool_calls: list[dict] = field(default_factory=list)
    # Each tool_call: {"name": "tool_name", "args": {...}, "output": "JSON string"}
    customer_context: dict = field(default_factory=dict)
    # Known customer info: {name, gender, project_interest, phone, ...}
    variations: int = 1               # How many wording variations to generate
    notes: str = ""                   # Special instructions for this scenario


# ─── Project codes ────────────────────────────────────────────────────────────
PROJECTS = ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC"]
PROJECT_NAMES = {
    "NCTH": "Noble Crystal Tây Hồ",
    "NCLB": "Noble Crystal Long Biên",
    "NPLB": "Noble Palace Long Biên",
    "NTTL": "Noble Palace Tây Thăng Long",
    "SSLC": "Sunshine Legend City",
}

# ─── Pre-computed tool outputs (from mock services) ──────────────────────────

# --- Project Overview outputs (from MongoDB project_du_an via structured_data) ---
PROJECT_OVERVIEW = {
    "NCTH": json.dumps({
        "code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ",
        "district": "Tây Hồ Tây, Ciputra, Hà Nội", "type": "Sky villa cao tầng",
        "units": 955, "unit_types": "110 căn hộ đơn tầng + 845 duplex sky villa 300-600m²",
        "floors": 40, "towers": 5, "clusters": [],
        "highlights": [
            "Lấy cảm hứng từ Atlantis Dubai và Marina Bay Sands Singapore",
            "Bãi biển nhân tạo Crystal Lagoon 7.200m²",
            "Kính low-E 3 lớp cách nhiệt",
            "Phố mua sắm trên cao 500m (tầng 4-5)",
            "Quản lý bởi WorldHotels (top 10 thế giới, 80 năm kinh nghiệm)",
        ],
        "management": "WorldHotels",
        "nearby": ["Hồ Tây", "Lotte Mall West Lake", "UNIS Hanoi", "Maple Bear"],
    }, ensure_ascii=False),
    "NCLB": json.dumps({
        "code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên",
        "district": "Phúc Đồng, Long Biên, Hà Nội", "type": "Sky villa cao tầng",
        "units": 413, "unit_types": "Duplex 1-4 phòng ngủ, 95-305m²",
        "floors": 17, "towers": ["Emirates", "Atlantis"], "clusters": [],
        "highlights": [
            "100% căn duplex có bể bơi riêng và thang máy riêng",
            "View trực diện sân golf 119ha tiêu chuẩn PGA 27 hố",
            "Hệ thống đỗ xe tự động Autobot (đầu tiên tại Việt Nam)",
            "Thang máy riêng cho siêu xe",
            "Smart home điều khiển giọng nói, Face ID",
        ],
        "management": "Noble",
        "nearby": ["Vinhomes Riverside", "AEON Mall Long Biên", "Sân golf Long Biên", "Vinschool"],
    }, ensure_ascii=False),
    "NPLB": json.dumps({
        "code": "NPLB", "name": "Noble Palace Long Biên", "region": "Long Biên",
        "district": "Long Biên, Hà Nội", "type": "Biệt thự châu Âu",
        "units": 172, "unit_types": "Song lập 125-370m², 4 tầng + mezzanine + hầm",
        "clusters": ["A4 Venus (80 căn)", "A7 Artemis (92 căn)"],
        "highlights": [
            "Kiến trúc cổ điển châu Âu: Hy Lạp, La Mã, Baroque, Phục Hưng",
            "Mỗi căn có bể bơi riêng",
            "Smart home Face ID, khóa thông minh",
            "Quản lý tiêu chuẩn 5 sao quốc tế",
            "Quảng trường Concorde, vườn Verona",
        ],
        "management": "Noble",
        "nearby": ["Vinschool", "Vinmec", "AEON Mall", "Sân golf Long Biên"],
    }, ensure_ascii=False),
    "NTTL": json.dumps({
        "code": "NTTL", "name": "Noble Palace Tây Thăng Long", "region": "Tây Thăng Long",
        "district": "Tân Lập, Đan Phượng, Hà Nội", "type": "Khu đô thị hỗn hợp",
        "units": 2448,
        "clusters": [
            "LEGACY (623 căn) - nghệ thuật/văn hóa",
            "WONDER (908 căn) - thể thao/giải trí",
            "HARMONY (496 căn) - sức khỏe/wellness",
            "VICTORY (421 căn) - giáo dục",
        ],
        "highlights": [
            "Quy mô 42ha trong tổng 77ha",
            "Regal Academy trường quốc tế tại chỗ",
            "Presidential Health Center bệnh viện 5 sao",
            "Noble Opera House nhà hát",
            "Smart city AI, robot phục vụ, đỗ xe thông minh",
            "101+ tiện ích",
        ],
        "management": "Noble",
        "nearby": ["Đại lộ Tây Thăng Long", "Hồ Tây", "Sân golf Long Biên", "Mỹ Đình"],
    }, ensure_ascii=False),
    "SSLC": json.dumps({
        "code": "SSLC", "name": "Sunshine Legend City", "region": "Văn Giang",
        "district": "Văn Giang, Hưng Yên", "type": "Khu đô thị hỗn hợp",
        "highlights": [
            "Khu A - Khu Đô thị phía Đông huyện Văn Giang",
            "Chủ đầu tư: Công ty CP Phát triển Đầu tư Xây dựng Bách Giang - DCI",
            "GPXD hạ tầng kỹ thuật: 14/02/2025",
            "Đã có quy hoạch 1/500",
            "Sổ đỏ do Sở TNMT Hà Nội cấp",
            "Căn hộ + shophouse + biệt thự liền kề",
        ],
        "management": "Noble",
        "nearby": ["Văn Giang", "Hưng Yên", "Vinhomes Ocean Park"],
    }, ensure_ascii=False),
}

# --- Pricing outputs (from structured_data_service.py) ---
PRICING = {
    "NCTH": json.dumps({
        "project": "NCTH", "results_count": 2, "results": [
            {"type": "2PN", "category": "cao tầng", "area_min_m2": 70.0, "area_max_m2": 88.0,
             "price_from_vnd": 8_000_000_000, "price_to_vnd": 14_000_000_000,
             "price_per_m2_vnd": 120_000_000, "total_units": 80, "available_units": 20},
            {"type": "3PN", "category": "cao tầng", "area_min_m2": 100.0, "area_max_m2": 130.0,
             "price_from_vnd": 12_000_000_000, "price_to_vnd": 25_000_000_000,
             "price_per_m2_vnd": 140_000_000, "total_units": 40, "available_units": 8},
        ],
    }, ensure_ascii=False),
    "NCLB": json.dumps({
        "project": "NCLB", "results_count": 2, "results": [
            {"type": "2PN", "category": "cao tầng", "area_min_m2": 68.0, "area_max_m2": 85.0,
             "price_from_vnd": 4_500_000_000, "price_to_vnd": 9_000_000_000,
             "price_per_m2_vnd": 75_000_000, "total_units": 150, "available_units": 60},
            {"type": "3PN", "category": "cao tầng", "area_min_m2": 90.0, "area_max_m2": 110.0,
             "price_from_vnd": 7_000_000_000, "price_to_vnd": 18_000_000_000,
             "price_per_m2_vnd": 90_000_000, "total_units": 80, "available_units": 25},
        ],
    }, ensure_ascii=False),
    "NPLB": json.dumps({
        "project": "NPLB", "results_count": 3, "results": [
            {"type": "1PN", "category": "cao tầng", "area_min_m2": 45.0, "area_max_m2": 55.0,
             "price_from_vnd": 2_800_000_000, "price_to_vnd": 4_000_000_000,
             "price_per_m2_vnd": 60_000_000, "total_units": 200, "available_units": 80},
            {"type": "2PN", "category": "cao tầng", "area_min_m2": 65.5, "area_max_m2": 75.2,
             "price_from_vnd": 3_200_000_000, "price_to_vnd": 4_500_000_000,
             "price_per_m2_vnd": 48_000_000, "total_units": 120, "available_units": 45},
            {"type": "3PN", "category": "cao tầng", "area_min_m2": 88.0, "area_max_m2": 100.0,
             "price_from_vnd": 5_000_000_000, "price_to_vnd": 8_000_000_000,
             "price_per_m2_vnd": 65_000_000, "total_units": 60, "available_units": 20},
        ],
    }, ensure_ascii=False),
    "NTTL": json.dumps({
        "project": "NTTL", "results_count": 2, "results": [
            {"type": "1PN", "category": "cao tầng", "area_min_m2": 40.0, "area_max_m2": 50.0,
             "price_from_vnd": 1_800_000_000, "price_to_vnd": 2_800_000_000,
             "price_per_m2_vnd": 45_000_000, "total_units": 250, "available_units": 120},
            {"type": "2PN", "category": "cao tầng", "area_min_m2": 60.0, "area_max_m2": 75.0,
             "price_from_vnd": 2_800_000_000, "price_to_vnd": 5_000_000_000,
             "price_per_m2_vnd": 50_000_000, "total_units": 180, "available_units": 90},
        ],
    }, ensure_ascii=False),
    "SSLC": json.dumps({
        "project": "SSLC", "results_count": 2, "results": [
            {"type": "2PN", "category": "cao tầng", "area_min_m2": 65.0, "area_max_m2": 80.0,
             "price_from_vnd": 3_500_000_000, "price_to_vnd": 7_000_000_000,
             "price_per_m2_vnd": 58_000_000, "total_units": 200, "available_units": 75},
            {"type": "3PN", "category": "cao tầng", "area_min_m2": 85.0, "area_max_m2": 105.0,
             "price_from_vnd": 5_500_000_000, "price_to_vnd": 16_000_000_000,
             "price_per_m2_vnd": 78_000_000, "total_units": 100, "available_units": 35},
        ],
    }, ensure_ascii=False),
}

# --- Payment plans ---
PAYMENT_PLANS = {
    "NPLB": json.dumps({"project": "NPLB", "plans": [
        {"name": "Thanh toán tiêu chuẩn", "plan_type": "STANDARD", "discount_percent": 0,
         "installments": [
             {"order_index": 1, "milestone_desc": "Ký HĐMB", "percent": 30},
             {"order_index": 2, "milestone_desc": "Hoàn thiện móng", "percent": 20},
             {"order_index": 3, "milestone_desc": "Bàn giao", "percent": 50},
         ]},
        {"name": "Thanh toán sớm 95%", "plan_type": "EARLY_PAYMENT", "discount_percent": 3.5,
         "installments": [
             {"order_index": 1, "milestone_desc": "Ký HĐMB, thanh toán 95%", "percent": 95},
             {"order_index": 2, "milestone_desc": "Bàn giao", "percent": 5},
         ]},
    ]}, ensure_ascii=False),
    "NCTH": json.dumps({"project": "NCTH", "plans": [
        {"name": "Thanh toán tiêu chuẩn", "plan_type": "STANDARD", "discount_percent": 0,
         "installments": [
             {"order_index": 1, "milestone_desc": "Ký HĐMB", "percent": 30},
             {"order_index": 2, "milestone_desc": "Hoàn thiện kết cấu", "percent": 30},
             {"order_index": 3, "milestone_desc": "Bàn giao", "percent": 40},
         ]},
    ]}, ensure_ascii=False),
}

# --- Loan policies ---
LOAN_POLICIES = {
    "NPLB": json.dumps({"project": "NPLB", "banks": [
        {"bank_name": "Vietcombank", "interest_rate_year": 8.5, "standard_rate_year": 10.5,
         "preferential_months": 24, "max_ltv_percent": 70, "max_term_years": 25},
        {"bank_name": "Techcombank", "interest_rate_year": 8.0, "standard_rate_year": 10.2,
         "preferential_months": 18, "max_ltv_percent": 70, "max_term_years": 25},
    ]}, ensure_ascii=False),
    "NCTH": json.dumps({"project": "NCTH", "banks": [
        {"bank_name": "VPBank", "interest_rate_year": 7.9, "standard_rate_year": 10.0,
         "preferential_months": 24, "max_ltv_percent": 65, "max_term_years": 20},
    ]}, ensure_ascii=False),
}

# --- Promotions ---
PROMOTIONS = {
    "NPLB": json.dumps({"project": "NPLB", "active_count": 2, "promotions": [
        {"name": "Chiết khấu thanh toán sớm", "promotion_type": "DISCOUNT_PERCENT",
         "discount_value_percent": 3.5, "valid_until": "2026-06-30"},
        {"name": "Gói nội thất bếp cao cấp", "promotion_type": "GIFT",
         "discount_value_percent": None, "valid_until": "2026-05-31"},
    ]}, ensure_ascii=False),
    "NCTH": json.dumps({"project": "NCTH", "active_count": 1, "promotions": [
        {"name": "Chiết khấu 2% cho khách VIP", "promotion_type": "DISCOUNT_PERCENT",
         "discount_value_percent": 2.0, "valid_until": "2026-12-31"},
    ]}, ensure_ascii=False),
    "NTTL": json.dumps({"project": "NTTL", "active_count": 1, "promotions": [
        {"name": "Hỗ trợ lãi suất 2 năm đầu", "promotion_type": "CASHBACK",
         "discount_value_percent": None, "valid_until": "2026-09-30"},
    ]}, ensure_ascii=False),
}

# --- Fees ---
FEES = {
    "NCTH": json.dumps({"booking_fee_vnd": 100_000_000, "hold_duration_hours": 48,
                         "vat_percent": 10, "maintenance_fee_per_m2": 1_500_000,
                         "service_fee_per_m2_year": 35_000}, ensure_ascii=False),
    "NCLB": json.dumps({"booking_fee_vnd": 70_000_000, "hold_duration_hours": 48,
                         "vat_percent": 10, "maintenance_fee_per_m2": 1_300_000,
                         "service_fee_per_m2_year": 30_000}, ensure_ascii=False),
    "NPLB": json.dumps({"booking_fee_vnd": 50_000_000, "hold_duration_hours": 48,
                         "vat_percent": 10, "maintenance_fee_per_m2": 1_200_000,
                         "service_fee_per_m2_year": 25_000}, ensure_ascii=False),
    "NTTL": json.dumps({"booking_fee_vnd": 30_000_000, "hold_duration_hours": 48,
                         "vat_percent": 10, "maintenance_fee_per_m2": 1_000_000,
                         "service_fee_per_m2_year": 22_000}, ensure_ascii=False),
    "SSLC": json.dumps({"booking_fee_vnd": 60_000_000, "hold_duration_hours": 48,
                         "vat_percent": 10, "maintenance_fee_per_m2": 1_300_000,
                         "service_fee_per_m2_year": 28_000}, ensure_ascii=False),
}

# --- List projects ---
LIST_ALL_PROJECTS = json.dumps({"count": 5, "projects": [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "type": "Sky villa cao tầng", "region": "Long Biên"},
    {"code": "NPLB", "name": "Noble Palace Long Biên", "type": "Biệt thự châu Âu", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "type": "Sky villa cao tầng", "region": "Tây Hồ"},
    {"code": "NTTL", "name": "Noble Palace Tây Thăng Long", "type": "Khu đô thị hỗn hợp", "region": "Tây Thăng Long"},
    {"code": "SSLC", "name": "Sunshine Legend City", "type": "Khu đô thị hỗn hợp", "region": "Văn Giang"},
]}, ensure_ascii=False)

# --- Check availability (mock) ---
CHECK_AVAILABILITY = json.dumps({
    "project": "NCTH",
    "available_dates": ["21/04/2026", "22/04/2026", "23/04/2026", "24/04/2026",
                        "25/04/2026", "28/04/2026", "29/04/2026", "30/04/2026"],
    "slots": ["09:00 - 10:00", "10:00 - 11:00", "14:00 - 15:00", "15:00 - 16:00"],
    "note": "Các khung giờ khả dụng trong mười bốn ngày tới (ngày làm việc).",
}, ensure_ascii=False)

# --- Booking state ---
BOOKING_STATE_EMPTY = json.dumps({
    "state": "COLLECTING", "collected": {},
    "missing": ["customer_name", "phone_number", "project_interest", "preferred_date", "preferred_slot"],
    "all_fields": ["customer_name", "phone_number", "project_interest", "preferred_date", "preferred_slot"],
}, ensure_ascii=False)

BOOKING_STATE_FULL = json.dumps({
    "state": "CONFIRM",
    "collected": {"customer_name": "Nguyễn Minh", "phone_number": "0987654321",
                  "project_interest": "NCTH", "preferred_date": "21/04/2026",
                  "preferred_slot": "09:00 - 10:00"},
    "missing": [],
    "all_fields": ["customer_name", "phone_number", "project_interest", "preferred_date", "preferred_slot"],
}, ensure_ascii=False)

# --- Schedule viewing result ---
SCHEDULE_VIEWING_OK = json.dumps({
    "status": "confirmed", "booking_id": "APT-20260421-001",
    "customer_name": "Nguyễn Minh", "phone": "0987654321",
    "project": "Noble Crystal Tây Hồ", "date": "21/04/2026", "time": "09:00",
    "message": "Lịch tham quan đã được xác nhận.",
}, ensure_ascii=False)

# --- CRM outputs ---
CRM_LOOKUP_FOUND = json.dumps({
    "found": True, "customer_id": 1001, "name": "Nguyễn Văn A", "sex": "male",
    "has_cccd": True,
    "contracts": [{"contract_code": "HD-NCTH-001", "project": "NCTH", "unit": "A-1205"}],
}, ensure_ascii=False)

CRM_LOOKUP_NOT_FOUND = json.dumps({"found": False}, ensure_ascii=False)

CONTRACT_INFO = json.dumps({
    "contract_code": "HD-NCTH-001", "project": "NCTH", "unit": "A-1205",
    "contract_value": 4_200_000_000, "sign_date": "2025-06-15",
    "payments_summary": {"total_paid": 1_260_000_000, "total_remaining": 2_940_000_000, "paid_percent": 30},
    "warranty": {"duration_months": 24, "expiry": "2028-01-01"},
    "handover_schedule": {"expected_date": "2026-12-31", "actual_date": None},
}, ensure_ascii=False)

PAYMENT_SCHEDULE = json.dumps({
    "installments": [
        {"order": 1, "milestone": "Ký HĐMB", "percent": 30,
         "amount": 1_260_000_000, "due_date": "2025-06-15",
         "paid_date": "2025-06-14", "status": "paid"},
        {"order": 2, "milestone": "Hoàn thiện tầng 5", "percent": 20,
         "amount": 840_000_000, "due_date": "2026-03-31",
         "paid_date": None, "status": "pending"},
        {"order": 3, "milestone": "Bàn giao", "percent": 50,
         "amount": 2_100_000_000, "due_date": "2026-12-31",
         "paid_date": None, "status": "pending"},
    ],
    "total_paid": 1_260_000_000, "total_remaining": 2_940_000_000,
}, ensure_ascii=False)

VERIFY_OK = json.dumps({"verified": True, "contracts": [
    {"contract_code": "HD-NCTH-001", "project": "NCTH", "unit": "A-1205"},
]}, ensure_ascii=False)

VERIFY_FAIL = json.dumps({"verified": False, "attempts_remaining": 1}, ensure_ascii=False)
VERIFY_BLOCKED = json.dumps({
    "verified": False, "max_attempts_reached": True,
    "message": "Đã xác minh sai hai lần. Vui lòng liên hệ hotline 18006298.",
}, ensure_ascii=False)

TICKET_CREATED = json.dumps({
    "ticket_code": "TK-20260413", "ticket_type": "MAINTENANCE",
    "customer_id": 1001, "contract_code": "HD-NCTH-001",
    "severity": "high", "department": "Kỹ thuật",
    "details": "Rò rỉ nước tại phòng tắm tầng trên",
    "email_sent": True, "email_to": "tech@noblex.vn", "sla_hours": 24,
}, ensure_ascii=False)

CERTIFICATE_STATUS = json.dumps({"certificates": [
    {"type_display": "Sổ hồng (Giấy chứng nhận quyền sử dụng đất)",
     "status_display": "Đang xử lý — dự kiến Q3/2026",
     "issued_date": None,
     "notes": "Hồ sơ đã nộp Sở TN&MT ngày 2026-03-01"},
]}, ensure_ascii=False)

ESCALATE_CHECK = json.dumps({
    "has_name": True, "has_phone": True, "transfer_ready": True, "working_hours": True,
}, ensure_ascii=False)

ESCALATE_TRANSFER = json.dumps({
    "status": "transfer_completed", "department": "CVTV", "priority": "normal",
    "summary": "Khách: Nguyễn Minh, SĐT: 0987654321. Quan tâm dự án NCTH. KH muốn gặp chuyên viên để tư vấn trực tiếp.",
    "working_hours": True, "message": "Dạ, em sẽ kết nối chuyên viên ngay ạ.",
}, ensure_ascii=False)

ESCALATE_URGENT = json.dumps({
    "status": "transfer_completed", "department": "Kỹ thuật", "priority": "urgent",
    "summary": "Khách: Nguyễn Văn A, SĐT: 0987654321. HĐ HD-NCTH-001. Sự cố ngập tầng hầm, cần xử lý khẩn.",
    "working_hours": True, "message": "Dạ, em sẽ kết nối chuyên viên ngay ạ.",
}, ensure_ascii=False)

# --- RAG mock outputs (simulated noble_search) ---
RAG_NCTH_OVERVIEW = (
    "Noble Crystal Tây Hồ tọa lạc tại vị trí đắc địa Tây Hồ Tây, khu đô thị Ciputra. "
    "Dự án gồm 5 tòa tháp 40 tầng với 955 căn hộ cao cấp. Điểm nhấn là bãi biển nhân tạo "
    "Crystal Lagoon rộng 7.200m², phố mua sắm trên cao 500m. Quản lý bởi WorldHotels — "
    "top 10 thương hiệu khách sạn thế giới với 80 năm kinh nghiệm. [NCTH-001]"
)
RAG_NCLB_LOCATION = (
    "Noble Crystal Long Biên tọa lạc tại Phúc Đồng, Long Biên, Hà Nội. "
    "Dự án có view trực diện sân golf quốc tế Long Biên 119ha tiêu chuẩn PGA 27 hố. "
    "Cách AEON Mall Long Biên 5 phút, Vinhomes Riverside 3 phút. "
    "Kết nối thuận tiện qua cầu Vĩnh Tuy, cầu Chương Dương. [NCLB-LOC-001]"
)
RAG_LEGAL_NCTH = (
    "Noble Crystal Tây Hồ đã có đầy đủ pháp lý: Quyết định đầu tư, Giấy phép xây dựng, "
    "Quy hoạch chi tiết 1/500. Sổ hồng lâu dài cho căn hộ. Hình thức sở hữu: chung cư sở hữu "
    "lâu dài. Chủ đầu tư: NobleX Development. [NCTH-LEGAL-001]"
)
RAG_PROGRESS_NCTH = (
    "Tiến độ Noble Crystal Tây Hồ: Tòa 1 và 2 đã hoàn thiện kết cấu, đang nội thất. "
    "Tòa 3-5 đang xây dựng tầng 25-30. Dự kiến bàn giao tòa 1-2 quý 4/2026, "
    "tòa 3-5 quý 2/2027. [NCTH-PROGRESS-001]"
)
RAG_DEVELOPER = (
    "NobleX Development là chủ đầu tư bất động sản hạng hiệu tại Việt Nam. "
    "Đã phát triển nhiều dự án cao cấp tại Hà Nội với tiêu chuẩn quốc tế. "
    "Đối tác quản lý: WorldHotels (top 10 thế giới). [NOBLE-DEV-001]"
)
RAG_AMENITIES_NCTH = (
    "Tiện ích nội khu Noble Crystal Tây Hồ: Crystal Lagoon 7.200m², phố mua sắm trên cao, "
    "hồ bơi infinity pool tầng thượng, phòng gym, spa, nhà hàng 5 sao, "
    "khu vui chơi trẻ em, vườn zen, BBQ garden. Tiện ích ngoại khu: "
    "Lotte Mall West Lake, UNIS Hanoi, Maple Bear, bệnh viện Vinmec. [NCTH-AMEN-001]"
)
RAG_INVESTMENT = (
    "Tiềm năng đầu tư khu vực Tây Hồ Tây: giá đất tăng trung bình 15-20%/năm trong 3 năm qua. "
    "Hạ tầng metro line 2 đang triển khai. Khu vực quốc tế hóa cao, "
    "nhu cầu cho thuê ổn định từ chuyên gia nước ngoài. [INVEST-001]"
)


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════


def build_all_scenarios() -> list[Scenario]:
    """Build the complete list of scenarios."""
    scenarios: list[Scenario] = []

    # ── 01_ROUTER ─────────────────────────────────────────────────────────────
    scenarios.append(Scenario(
        id="01_greeting",
        agent="router", skill="noble-router", intent="SYS_GREETING",
        category="01_router",
        customer_query="Xin chào",
        tool_calls=[],
        variations=2,
        notes="Chào hỏi + menu 4 lựa chọn. Không switch.",
    ))
    scenarios.append(Scenario(
        id="02_greeting_informal",
        agent="router", skill="noble-router", intent="SYS_GREETING",
        category="01_router",
        customer_query="Chào em, anh muốn hỏi chút",
        tool_calls=[],
        customer_context={"gender": "M"},
        variations=1,
        notes="Chào informal, suy luận gender=M. Vẫn menu 4 lựa chọn.",
    ))

    # Pre-sale routes for each project
    for code in PROJECTS:
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"03_presale_route_{code}",
            agent="router", skill="noble-router", intent="PRE_SALE_ROUTE",
            category="01_router",
            customer_query=f"Cho tôi hỏi về {name}",
            tool_calls=[
                {"name": "update_customer", "args": {"project_interest": code},
                 "output": json.dumps({"success": True, "updated_fields": ["project_interest"]})},
                {"name": "switch_agent", "args": {"agent_id": "consultant", "query": f"KH hỏi thông tin dự án {code}"},
                 "output": json.dumps({"status": "agent_switched", "agent_id": "consultant"})},
            ],
            variations=1,
        ))

    scenarios.append(Scenario(
        id="04_postsale_route",
        agent="router", skill="noble-router", intent="POST_SALE_ROUTE",
        category="01_router",
        customer_query="Tôi đã mua căn ở Noble Crystal Tây Hồ, muốn hỏi tiến độ bàn giao",
        tool_calls=[
            {"name": "switch_agent", "args": {"agent_id": "support", "query": "KH đã mua tại NCTH, hỏi tiến độ bàn giao"},
             "output": json.dumps({"status": "agent_switched", "agent_id": "support"})},
        ],
        variations=1,
    ))
    scenarios.append(Scenario(
        id="05_unclear_need",
        agent="router", skill="noble-router", intent="SYS_UNCLEAR",
        category="01_router",
        customer_query="Anh đang kiếm nhà 3 ngủ",
        tool_calls=[],
        customer_context={"gender": "M"},
        variations=1,
        notes="Chưa biết dự án → hỏi clarify, liệt kê 5 dự án.",
    ))
    scenarios.append(Scenario(
        id="06_end_chat_step1",
        agent="router", skill="noble-router", intent="SYS_END_CHAT",
        category="01_router",
        customer_query="Cảm ơn em, anh đủ thông tin rồi",
        tool_calls=[],
        customer_context={"name": "Minh", "gender": "M"},
        variations=1,
        notes="Bước 1 kết thúc: hỏi còn cần hỗ trợ không.",
    ))
    scenarios.append(Scenario(
        id="07_end_chat_step2",
        agent="router", skill="noble-router", intent="SYS_END_CHAT",
        category="01_router",
        customer_query="Không cần nữa đâu em, tạm biệt",
        tool_calls=[],
        customer_context={"name": "Minh", "gender": "M"},
        variations=1,
        notes="Bước 2 kết thúc: cảm ơn + chào.",
    ))
    scenarios.append(Scenario(
        id="08_multi_intent",
        agent="router", skill="noble-router", intent="MULTI_INTENT",
        category="01_router",
        customer_query="Anh muốn hỏi giá NCLB, rồi kiểm tra hợp đồng cũ luôn",
        tool_calls=[
            {"name": "update_customer", "args": {"project_interest": "NCLB"},
             "output": json.dumps({"success": True, "updated_fields": ["project_interest"]})},
            {"name": "switch_agent", "args": {"agent_id": "consultant", "query": "KH hỏi giá NCLB, sau đó cần kiểm tra HĐ cũ"},
             "output": json.dumps({"status": "agent_switched", "agent_id": "consultant"})},
        ],
        customer_context={"gender": "M"},
        variations=1,
        notes="Nhiều yêu cầu: liệt kê + route yêu cầu đầu.",
    ))
    scenarios.append(Scenario(
        id="09_off_topic",
        agent="router", skill="noble-router", intent="OFF_TOPIC",
        category="01_router",
        customer_query="Em dịch giúp anh bài này sang tiếng Anh được không?",
        tool_calls=[],
        customer_context={"gender": "M"},
        variations=1,
        notes="Ngoài phạm vi → từ chối mềm.",
    ))

    # ── 02_CONSULTANT_INFO ─────────────────────────────────────────────────────
    for code in PROJECTS:
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"01_overview_{code}",
            agent="consultant", skill="consultant-info", intent="INQ_PROJECT_OVERVIEW",
            category="02_consultant_info",
            customer_query=f"Giới thiệu cho anh về dự án {name}",
            tool_calls=[
                {"name": "get_project_overview", "args": {"project_code": code},
                 "output": PROJECT_OVERVIEW[code]},
                {"name": "kb_search", "args": {"query": f"{name} tổng quan", "project_filter": code},
                 "output": RAG_NCTH_OVERVIEW if code == "NCTH" else f"Dự án {name} là một trong những dự án cao cấp hàng đầu của NobleX tại khu vực {PROJECT_NAMES[code].split()[-1]}. [REF-{code}-001]"},
            ],
            customer_context={"name": "Minh", "gender": "M", "project_interest": code},
            variations=1,
        ))

    for code in PROJECTS[:3]:  # Top 3 projects for location
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"02_location_{code}",
            agent="consultant", skill="consultant-info", intent="INQ_LOCATION",
            category="02_consultant_info",
            customer_query=f"Dự án {name} ở đâu vậy em?",
            tool_calls=[
                {"name": "kb_search", "args": {"query": f"vị trí {name}", "project_filter": code},
                 "output": RAG_NCLB_LOCATION if code == "NCLB" else f"Dự án {name} tọa lạc tại vị trí trung tâm khu vực, kết nối thuận tiện. [LOC-{code}-001]"},
                {"name": "kb_search", "args": {"query": f"kết nối giao thông {name}", "project_filter": code},
                 "output": f"Giao thông kết nối: đường chính, metro, cầu vượt. Cách trung tâm 15-20 phút. [TRAFFIC-{code}-001]"},
            ],
            customer_context={"name": "Minh", "gender": "M", "project_interest": code},
        ))

    # Amenities for NCTH
    scenarios.append(Scenario(
        id="03_amenities_NCTH",
        agent="consultant", skill="consultant-info", intent="INQ_AMENITIES",
        category="02_consultant_info",
        customer_query="Tiện ích Noble Crystal Tây Hồ có những gì em?",
        tool_calls=[
            {"name": "kb_search", "args": {"query": "tiện ích Noble Crystal Tây Hồ", "project_filter": "NCTH"},
             "output": RAG_AMENITIES_NCTH},
            {"name": "get_project_overview", "args": {"project_code": "NCTH"},
             "output": PROJECT_OVERVIEW["NCTH"]},
        ],
        customer_context={"name": "Hương", "gender": "F", "project_interest": "NCTH"},
    ))

    # Legal for NCTH
    scenarios.append(Scenario(
        id="04_legal_NCTH",
        agent="consultant", skill="consultant-info", intent="INQ_LEGAL",
        category="02_consultant_info",
        customer_query="Pháp lý dự án NCTH thế nào em?",
        tool_calls=[
            {"name": "get_project_overview", "args": {"project_code": "NCTH"},
             "output": PROJECT_OVERVIEW["NCTH"]},
            {"name": "kb_search", "args": {"query": "pháp lý Noble Crystal Tây Hồ"},
             "output": RAG_LEGAL_NCTH},
            {"name": "kb_search", "args": {"query": "sổ hồng GPXD Noble Crystal Tây Hồ"},
             "output": "GPXD số 123/GPXD ngày 15/03/2024. QĐ đầu tư số 456/QĐ-UBND. Sổ hồng lâu dài. [NCTH-GPXD-001]"},
        ],
        customer_context={"name": "Lan", "gender": "F", "project_interest": "NCTH"},
    ))

    # Progress for NCTH
    scenarios.append(Scenario(
        id="05_progress_NCTH",
        agent="consultant", skill="consultant-info", intent="INQ_PROGRESS",
        category="02_consultant_info",
        customer_query="Tiến độ Noble Crystal Tây Hồ đến đâu rồi em?",
        tool_calls=[
            {"name": "kb_search", "args": {"query": "tiến độ xây dựng Noble Crystal Tây Hồ"},
             "output": RAG_PROGRESS_NCTH},
            {"name": "kb_search", "args": {"query": "tiến độ bàn giao Noble Crystal Tây Hồ"},
             "output": "Dự kiến bàn giao tòa 1-2 quý 4/2026, tòa 3-5 quý 2/2027. [NCTH-HANDOVER-001]"},
        ],
        customer_context={"name": "Tuấn", "gender": "M", "project_interest": "NCTH"},
    ))

    # Developer
    scenarios.append(Scenario(
        id="06_developer",
        agent="consultant", skill="consultant-info", intent="INQ_DEVELOPER",
        category="02_consultant_info",
        customer_query="Chủ đầu tư Noble là ai vậy em?",
        tool_calls=[
            {"name": "kb_search", "args": {"query": "chủ đầu tư NobleX"},
             "output": RAG_DEVELOPER},
            {"name": "kb_search", "args": {"query": "dự án đã bàn giao NobleX"},
             "output": "NobleX đã bàn giao thành công nhiều dự án cao cấp tại Hà Nội. [NOBLE-TRACK-001]"},
        ],
        customer_context={"name": "Dũng", "gender": "M"},
    ))

    # Compare NCLB vs NCTH
    scenarios.append(Scenario(
        id="07_compare_NCLB_NCTH",
        agent="consultant", skill="consultant-info", intent="INQ_COMPARE",
        category="02_consultant_info",
        customer_query="So sánh Noble Crystal Long Biên với Noble Crystal Tây Hồ cho anh",
        tool_calls=[
            {"name": "get_project_overview", "args": {"project_code": "NCLB"},
             "output": PROJECT_OVERVIEW["NCLB"]},
            {"name": "get_project_overview", "args": {"project_code": "NCTH"},
             "output": PROJECT_OVERVIEW["NCTH"]},
        ],
        customer_context={"name": "Long", "gender": "M"},
    ))

    # Product type
    scenarios.append(Scenario(
        id="08_product_type_NCLB",
        agent="consultant", skill="consultant-info", intent="INQ_PRODUCT_TYPE",
        category="02_consultant_info",
        customer_query="Căn 3 phòng ngủ ở NCLB có gì đặc biệt em?",
        tool_calls=[
            {"name": "search_units", "args": {"project_code": "NCLB", "unit_type": "3PN"},
             "output": json.dumps([
                 {"unit_code": "A-0801", "type": "3PN", "wall_area_m2": 100.0, "clear_area_m2": 94.0,
                  "bedroom_count": 3, "direction": "Đông Nam", "floor": 8, "tower": "A",
                  "price_vnd": 7_000_000_000, "status": "available"},
             ], ensure_ascii=False)},
            {"name": "get_project_overview", "args": {"project_code": "NCLB"},
             "output": PROJECT_OVERVIEW["NCLB"]},
        ],
        customer_context={"name": "Hà", "gender": "F", "project_interest": "NCLB"},
    ))

    # ── 03_CONSULTANT_PRICING ──────────────────────────────────────────────────
    for code in PROJECTS:
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"01_price_list_{code}",
            agent="consultant", skill="consultant-pricing", intent="PRC_PRICE_LIST",
            category="03_consultant_pricing",
            customer_query=f"Giá căn hộ {name} bao nhiêu em?",
            tool_calls=[
                {"name": "get_project_financial", "args": {"project_code": code, "info_type": "pricing"},
                 "output": PRICING[code]},
            ],
            customer_context={"name": "Minh", "gender": "M", "project_interest": code},
        ))

    # Payment plans
    for code in ["NPLB", "NCTH"]:
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"02_payment_{code}",
            agent="consultant", skill="consultant-pricing", intent="PRC_PAYMENT",
            category="03_consultant_pricing",
            customer_query=f"Phương thức thanh toán {name} thế nào em?",
            tool_calls=[
                {"name": "get_project_financial", "args": {"project_code": code, "info_type": "payment_plans"},
                 "output": PAYMENT_PLANS[code]},
            ],
            customer_context={"name": "Hương", "gender": "F", "project_interest": code},
        ))

    # Promotions
    for code in ["NPLB", "NCTH", "NTTL"]:
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"03_promotion_{code}",
            agent="consultant", skill="consultant-pricing", intent="PRC_PROMOTION",
            category="03_consultant_pricing",
            customer_query=f"Ưu đãi {name} hiện có gì em?",
            tool_calls=[
                {"name": "get_project_financial", "args": {"project_code": code, "info_type": "promotions"},
                 "output": PROMOTIONS[code]},
                {"name": "kb_search", "args": {"query": f"ưu đãi khuyến mãi {name}", "project_filter": code},
                 "output": f"Ưu đãi hiện hành tại {name}: chiết khấu thanh toán sớm, quà tặng nội thất. [PROMO-{code}-001]"},
            ],
            customer_context={"name": "Tuấn", "gender": "M", "project_interest": code},
        ))

    # Loan policies
    for code in ["NPLB", "NCTH"]:
        name = PROJECT_NAMES[code]
        scenarios.append(Scenario(
            id=f"04_loan_{code}",
            agent="consultant", skill="consultant-pricing", intent="PRC_LOAN",
            category="03_consultant_pricing",
            customer_query=f"Vay ngân hàng mua {name} được không em?",
            tool_calls=[
                {"name": "get_project_financial", "args": {"project_code": code, "info_type": "loan_policies"},
                 "output": LOAN_POLICIES[code]},
                {"name": "kb_search", "args": {"query": f"chính sách vay {name}", "project_filter": code},
                 "output": f"Hỗ trợ vay ngân hàng lên đến 70% giá trị, lãi suất ưu đãi 2 năm đầu. [LOAN-{code}-001]"},
            ],
            customer_context={"name": "Dũng", "gender": "M", "project_interest": code},
        ))

    # Total cost
    scenarios.append(Scenario(
        id="05_total_cost_NCTH",
        agent="consultant", skill="consultant-pricing", intent="PRC_TOTAL_COST",
        category="03_consultant_pricing",
        customer_query="Tổng chi phí mua căn 2 phòng ngủ ở NCTH là bao nhiêu em?",
        tool_calls=[
            {"name": "get_project_financial", "args": {"project_code": "NCTH", "info_type": "pricing"},
             "output": PRICING["NCTH"]},
            {"name": "get_project_financial", "args": {"project_code": "NCTH", "info_type": "fees"},
             "output": FEES["NCTH"]},
        ],
        customer_context={"name": "Mai Anh", "gender": "F", "project_interest": "NCTH"},
        notes="Tính tổng: Giá bán + VAT + Phí bảo trì + Booking fee. Số bằng chữ.",
    ))

    # Compare price
    scenarios.append(Scenario(
        id="06_compare_price_NCLB_NCTH",
        agent="consultant", skill="consultant-pricing", intent="PRC_COMPARE_PRICE",
        category="03_consultant_pricing",
        customer_query="So sánh giá NCLB với NCTH cho anh",
        tool_calls=[
            {"name": "get_project_financial", "args": {"project_code": "NCLB", "info_type": "pricing"},
             "output": PRICING["NCLB"]},
            {"name": "get_project_financial", "args": {"project_code": "NCTH", "info_type": "pricing"},
             "output": PRICING["NCTH"]},
        ],
        customer_context={"name": "Cường", "gender": "M"},
    ))

    # Investment
    scenarios.append(Scenario(
        id="07_investment_NCTH",
        agent="consultant", skill="consultant-pricing", intent="PRC_INVESTMENT",
        category="03_consultant_pricing",
        customer_query="Đầu tư NCTH có lợi không em?",
        tool_calls=[
            {"name": "get_project_financial", "args": {"project_code": "NCTH", "info_type": "pricing"},
             "output": PRICING["NCTH"]},
            {"name": "kb_search", "args": {"query": "tiềm năng đầu tư Noble Crystal Tây Hồ"},
             "output": RAG_INVESTMENT},
        ],
        customer_context={"name": "Long", "gender": "M", "project_interest": "NCTH"},
        notes="KHÔNG đảm bảo lợi nhuận. Nói tiềm năng khu vực.",
    ))

    # ── 04_CONSULTANT_ADVISOR ──────────────────────────────────────────────────
    # Profile 1: Ở thực, 5 tỷ, 3PN
    scenarios.append(Scenario(
        id="01_advisor_profile1",
        agent="consultant", skill="consultant-advisor", intent="ADV_RECOMMEND",
        category="04_consultant_advisor",
        customer_query="Anh muốn mua nhà để ở, ngân sách khoảng 5 tỷ, cần 3 phòng ngủ",
        tool_calls=[
            {"name": "update_customer", "args": {"purpose": "ở", "budget": "5 tỷ", "bedroom_count": "3PN"},
             "output": json.dumps({"success": True, "updated_fields": ["purpose", "budget", "bedroom_count"]})},
            {"name": "match_projects", "args": {"purpose": "ở", "budget_max": 5_000_000_000, "bedrooms": 3},
             "output": json.dumps({
                 "projects": [
                     {"code": "NPLB", "name": "Noble Palace Long Biên", "region": "Long Biên", "type": "Biệt thự châu Âu"},
                     {"code": "NTTL", "name": "Noble Palace Tây Thăng Long", "region": "Tây Thăng Long", "type": "Khu đô thị hỗn hợp"},
                     {"code": "SSLC", "name": "Sunshine Legend City", "region": "Văn Giang", "type": "Khu đô thị hỗn hợp"},
                 ],
                 "customer_criteria": {"purpose": "ở", "budget_max": 5_000_000_000, "region": "", "bedrooms": 3},
             }, ensure_ascii=False)},
            {"name": "get_project_financial", "args": {"project_code": "NPLB", "info_type": "pricing"},
             "output": PRICING["NPLB"]},
            {"name": "get_project_financial", "args": {"project_code": "NTTL", "info_type": "pricing"},
             "output": PRICING["NTTL"]},
        ],
        customer_context={"name": "Minh", "gender": "M"},
    ))

    # Profile 2: Đầu tư, 10 tỷ, Long Biên
    scenarios.append(Scenario(
        id="02_advisor_profile2",
        agent="consultant", skill="consultant-advisor", intent="ADV_RECOMMEND",
        category="04_consultant_advisor",
        customer_query="Chị muốn đầu tư, ngân sách mười tỷ, khu vực Long Biên",
        tool_calls=[
            {"name": "update_customer", "args": {"purpose": "đầu tư", "budget": "10 tỷ", "preferred_area": "Long Biên"},
             "output": json.dumps({"success": True, "updated_fields": ["purpose", "budget", "preferred_area"]})},
            {"name": "match_projects", "args": {"purpose": "đầu tư", "budget_max": 10_000_000_000, "region": "Long Biên"},
             "output": json.dumps({
                 "projects": [
                     {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên", "type": "Sky villa cao tầng"},
                     {"code": "NPLB", "name": "Noble Palace Long Biên", "region": "Long Biên", "type": "Biệt thự châu Âu"},
                 ],
                 "customer_criteria": {"purpose": "đầu tư", "budget_max": 10_000_000_000, "region": "Long Biên"},
             }, ensure_ascii=False)},
            {"name": "get_project_financial", "args": {"project_code": "NCLB", "info_type": "pricing"},
             "output": PRICING["NCLB"]},
            {"name": "get_project_financial", "args": {"project_code": "NPLB", "info_type": "pricing"},
             "output": PRICING["NPLB"]},
        ],
        customer_context={"name": "Lan", "gender": "F"},
    ))

    # Collect 1 entity at a time
    scenarios.append(Scenario(
        id="03_advisor_collect_purpose",
        agent="consultant", skill="consultant-advisor", intent="ADV_COLLECT",
        category="04_consultant_advisor",
        customer_query="Anh muốn tư vấn mua nhà",
        tool_calls=[],
        customer_context={"name": "Hùng", "gender": "M"},
        notes="Hỏi mục đích: ở hay đầu tư. Chỉ hỏi 1 câu.",
    ))
    scenarios.append(Scenario(
        id="04_advisor_collect_budget",
        agent="consultant", skill="consultant-advisor", intent="ADV_COLLECT",
        category="04_consultant_advisor",
        customer_query="Anh mua để ở",
        tool_calls=[
            {"name": "update_customer", "args": {"purpose": "ở"},
             "output": json.dumps({"success": True, "updated_fields": ["purpose"]})},
        ],
        customer_context={"name": "Hùng", "gender": "M"},
        notes="Lưu purpose, hỏi tiếp ngân sách. Chỉ hỏi 1 câu.",
    ))

    # ── 05_CONSULTANT_BOOKING ──────────────────────────────────────────────────
    scenarios.append(Scenario(
        id="01_booking_init",
        agent="consultant", skill="consultant-booking", intent="BKG_INIT",
        category="05_consultant_booking",
        customer_query="Em đặt lịch xem Noble Crystal Tây Hồ cho anh",
        tool_calls=[
            {"name": "check_availability", "args": {"project_code": "NCTH"},
             "output": CHECK_AVAILABILITY},
            {"name": "update_customer", "args": {"project_interest": "NCTH"},
             "output": json.dumps({"success": True, "updated_fields": ["project_interest"]})},
        ],
        customer_context={"gender": "M", "project_interest": "NCTH"},
        variations=2,
        notes="Khởi tạo booking, hỏi họ tên.",
    ))
    scenarios.append(Scenario(
        id="02_booking_collect_name",
        agent="consultant", skill="consultant-booking", intent="BKG_COLLECT",
        category="05_consultant_booking",
        customer_query="Tên anh là Nguyễn Minh, số điện thoại không chín tám bảy sáu năm bốn ba hai một",
        tool_calls=[
            {"name": "update_booking_info", "args": {"customer_name": "Nguyễn Minh", "phone_number": "0987654321"},
             "output": json.dumps({"success": True, "updated_fields": ["customer_name", "phone_number"],
                                   "current_draft": {"customer_name": "Nguyễn Minh", "phone_number": "0987654321"}})},
        ],
        customer_context={"name": "Minh", "gender": "M", "project_interest": "NCTH"},
        notes="Lưu tên + SĐT, hỏi ngày muốn xem.",
    ))
    scenarios.append(Scenario(
        id="03_booking_confirm",
        agent="consultant", skill="consultant-booking", intent="BKG_CONFIRM",
        category="05_consultant_booking",
        customer_query="Ngày hai mươi mốt tháng tư, chín giờ sáng nhé",
        tool_calls=[
            {"name": "update_booking_info",
             "args": {"preferred_date": "21/04/2026", "preferred_slot": "09:00 - 10:00"},
             "output": json.dumps({"success": True, "updated_fields": ["preferred_date", "preferred_slot"],
                                   "current_draft": {"customer_name": "Nguyễn Minh", "phone_number": "0987654321",
                                                     "project_interest": "NCTH", "preferred_date": "21/04/2026",
                                                     "preferred_slot": "09:00 - 10:00"}})},
            {"name": "get_booking_state", "args": {}, "output": BOOKING_STATE_FULL},
        ],
        customer_context={"name": "Minh", "gender": "M", "project_interest": "NCTH"},
        notes="Đủ 5 trường → đọc xác nhận thông tin.",
    ))
    scenarios.append(Scenario(
        id="04_booking_done",
        agent="consultant", skill="consultant-booking", intent="BKG_DONE",
        category="05_consultant_booking",
        customer_query="Đúng rồi ạ, anh xác nhận",
        tool_calls=[
            {"name": "schedule_viewing",
             "args": {"customer_name": "Nguyễn Minh", "phone": "0987654321",
                      "project": "Noble Crystal Tây Hồ", "preferred_date": "21/04/2026",
                      "preferred_time": "09:00", "confirmed": True},
             "output": SCHEDULE_VIEWING_OK},
        ],
        customer_context={"name": "Minh", "gender": "M", "project_interest": "NCTH"},
        notes="Đặt lịch thành công, nói mã booking + SLA.",
    ))

    # ── 06_SUPPORT_CRM ─────────────────────────────────────────────────────────
    scenarios.append(Scenario(
        id="01_contract_inquiry",
        agent="support", skill="support-crm", intent="AFT_CONTRACT",
        category="06_support_crm",
        customer_query="Anh muốn kiểm tra hợp đồng, số điện thoại không chín tám bảy sáu năm bốn ba hai một",
        tool_calls=[
            {"name": "crm_lookup", "args": {"action": "lookup", "phone": "0987654321"},
             "output": CRM_LOOKUP_FOUND},
            {"name": "crm_lookup", "args": {"action": "contract", "contract_code": "HD-NCTH-001"},
             "output": CONTRACT_INFO},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
        notes="CRM lookup thành công → trả thông tin HĐ.",
    ))
    scenarios.append(Scenario(
        id="02_payment_schedule",
        agent="support", skill="support-crm", intent="AFT_PAYMENT",
        category="06_support_crm",
        customer_query="Anh còn phải đóng bao nhiêu tiền nữa?",
        tool_calls=[
            {"name": "crm_lookup", "args": {"action": "lookup", "phone": "0987654321"},
             "output": CRM_LOOKUP_FOUND},
            {"name": "crm_lookup", "args": {"action": "payment_schedule", "contract_code": "HD-NCTH-001"},
             "output": PAYMENT_SCHEDULE},
            {"name": "crm_lookup", "args": {"action": "contract", "contract_code": "HD-NCTH-001"},
             "output": CONTRACT_INFO},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
    ))
    scenarios.append(Scenario(
        id="03_delivery_status",
        agent="support", skill="support-crm", intent="AFT_DELIVERY",
        category="06_support_crm",
        customer_query="Bao giờ anh nhận nhà?",
        tool_calls=[
            {"name": "crm_lookup", "args": {"action": "lookup", "phone": "0987654321"},
             "output": CRM_LOOKUP_FOUND},
            {"name": "crm_lookup", "args": {"action": "contract", "contract_code": "HD-NCTH-001"},
             "output": CONTRACT_INFO},
            {"name": "kb_search", "args": {"query": "tiến độ bàn giao Noble Crystal Tây Hồ"},
             "output": "Dự kiến bàn giao tòa A quý 4/2026. [NCTH-HANDOVER-001]"},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
    ))
    scenarios.append(Scenario(
        id="04_maintenance",
        agent="support", skill="support-crm", intent="AFT_MAINTENANCE",
        category="06_support_crm",
        customer_query="Nhà anh bị rò rỉ nước ở phòng tắm, giúp anh xử lý với",
        tool_calls=[
            {"name": "crm_lookup", "args": {"action": "lookup", "phone": "0987654321"},
             "output": CRM_LOOKUP_FOUND},
            {"name": "crm_lookup", "args": {"action": "contract", "contract_code": "HD-NCTH-001"},
             "output": CONTRACT_INFO},
            {"name": "support_ticket", "args": {
                "action": "create", "ticket_type": "MAINTENANCE",
                "customer_id": "1001", "contract_code": "HD-NCTH-001",
                "details": "Rò rỉ nước tại phòng tắm tầng trên",
                "severity": "high", "department": "Kỹ thuật",
             }, "output": TICKET_CREATED},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
        notes="Còn bảo hành → tạo phiếu miễn phí, SLA 24h.",
    ))
    scenarios.append(Scenario(
        id="05_certificate",
        agent="support", skill="support-crm", intent="AFT_CERTIFICATE",
        category="06_support_crm",
        customer_query="Sổ hồng của anh đến đâu rồi em?",
        tool_calls=[
            {"name": "crm_lookup", "args": {"action": "lookup", "phone": "0987654321"},
             "output": CRM_LOOKUP_FOUND},
            {"name": "get_certificate_status", "args": {"contract_code": "HD-NCTH-001"},
             "output": CERTIFICATE_STATUS},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
    ))
    scenarios.append(Scenario(
        id="06_verify_ok",
        agent="support", skill="support-crm", intent="VERIFY_IDENTITY",
        category="06_support_crm",
        customer_query="CCCD của anh là không không một hai ba bốn năm sáu bảy tám chín không",
        tool_calls=[
            {"name": "verify_identity", "args": {"customer_id": "1001", "cccd": "001234567890"},
             "output": VERIFY_OK},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
        notes="Xác minh thành công.",
    ))
    scenarios.append(Scenario(
        id="07_verify_fail",
        agent="support", skill="support-crm", intent="VERIFY_IDENTITY",
        category="06_support_crm",
        customer_query="CCCD là không không chín tám bảy sáu năm bốn ba hai một không",
        tool_calls=[
            {"name": "verify_identity", "args": {"customer_id": "1001", "cccd": "009876543210"},
             "output": VERIFY_FAIL},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
        notes="Xác minh sai lần 1 → còn 1 lần.",
    ))
    scenarios.append(Scenario(
        id="08_crm_not_found",
        agent="support", skill="support-crm", intent="AFT_CONTRACT",
        category="06_support_crm",
        customer_query="Kiểm tra hợp đồng cho anh, số điện thoại không ba năm sáu bảy tám chín không một hai ba",
        tool_calls=[
            {"name": "crm_lookup", "args": {"action": "lookup", "phone": "0356789012"},
             "output": CRM_LOOKUP_NOT_FOUND},
        ],
        customer_context={"gender": "M"},
        notes="Không tìm thấy KH → hướng dẫn hotline.",
    ))

    # ── 07_SUPPORT_ESCALATION ──────────────────────────────────────────────────
    scenarios.append(Scenario(
        id="01_escalate_immediate",
        agent="support", skill="support-escalation", intent="ESC_IMMEDIATE",
        category="07_support_escalation",
        customer_query="Cho tôi gặp chuyên viên ngay!",
        tool_calls=[
            {"name": "escalate", "args": {"action": "transfer", "reason": "KH yêu cầu gặp chuyên viên trực tiếp",
                                           "department": "CVTV", "priority": "normal"},
             "output": ESCALATE_TRANSFER},
        ],
        customer_context={"name": "Minh", "gender": "M", "phone": "0987654321"},
        variations=2,
        notes="Chuyển ngay, không cần xác nhận.",
    ))
    scenarios.append(Scenario(
        id="02_escalate_implicit",
        agent="support", skill="support-escalation", intent="ESC_IMPLICIT",
        category="07_support_escalation",
        customer_query="Em ơi, anh giải thích nhiều lần rồi mà vẫn chưa hiểu",
        tool_calls=[
            {"name": "escalate", "args": {"action": "check_state"},
             "output": ESCALATE_CHECK},
        ],
        customer_context={"name": "Tuấn", "gender": "M", "phone": "0912345678"},
        notes="Hỏi xác nhận trước khi chuyển.",
    ))
    scenarios.append(Scenario(
        id="03_escalate_urgent",
        agent="support", skill="support-escalation", intent="ESC_URGENT",
        category="07_support_escalation",
        customer_query="Tầng hầm nhà anh bị ngập nước! Cần xử lý gấp!",
        tool_calls=[
            {"name": "escalate", "args": {"action": "transfer", "reason": "Sự cố ngập tầng hầm, cần xử lý khẩn cấp",
                                           "department": "Kỹ thuật", "priority": "urgent"},
             "output": ESCALATE_URGENT},
        ],
        customer_context={"name": "Văn A", "gender": "M", "phone": "0987654321"},
        notes="Sự cố khẩn cấp → chuyển ngay, priority=urgent.",
    ))
    scenarios.append(Scenario(
        id="04_escalate_outside_hours",
        agent="support", skill="support-escalation", intent="ESC_OUTSIDE_HOURS",
        category="07_support_escalation",
        customer_query="Anh muốn gặp chuyên viên tư vấn",
        tool_calls=[
            {"name": "escalate", "args": {"action": "transfer", "reason": "KH yêu cầu gặp CVTV",
                                           "department": "CVTV", "priority": "normal"},
             "output": json.dumps({
                 "status": "transfer_completed", "department": "CVTV", "priority": "normal",
                 "summary": "Khách: Minh, SĐT: 0987654321. KH muốn gặp CVTV.",
                 "working_hours": False,
                 "message": "Dạ, hiện ngoài giờ làm việc ạ. Chuyên viên sẽ liên hệ vào ngày làm việc tiếp theo ạ.",
             }, ensure_ascii=False)},
        ],
        customer_context={"name": "Minh", "gender": "M", "phone": "0987654321"},
        notes="Ngoài giờ → thông báo CVTV sẽ liên hệ sau.",
    ))

    return scenarios
