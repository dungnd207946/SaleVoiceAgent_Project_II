"""`contracts/` phải khớp nguồn — nếu không, repo FE canh parity với dữ liệu cũ.

Đây là nửa BE của cổng 3. Nửa FE là `tests/actions-parity.test.ts` bên repo
frontend, nó so `contracts/actions.json` (bản sao) với `src/lib/actions.ts`.

Vì sao cần cả hai nửa: artefact là thứ duy nhất đi được qua ranh giới hai repo.
Nửa này chứng minh artefact = nguồn; nửa kia chứng minh FE = artefact. Bắc cầu ra
FE = nguồn — với đúng một khoảng hở đã ghi ở contracts/README.md (bước copy tay).
"""

import json
from pathlib import Path

from scripts.gen_contracts import noi_dung_actions, noi_dung_audit_actions

from portal.core.auth.actions import ALL_ACTIONS
from portal.core.nhat_ky_ma import MA_TAT_CA

CONTRACTS = Path(__file__).resolve().parent.parent.parent / "contracts"
ACTIONS_JSON = CONTRACTS / "actions.json"
AUDIT_JSON = CONTRACTS / "audit-actions.json"


def test_artefact_ton_tai():
    assert ACTIONS_JSON.exists(), "thiếu contracts/actions.json — chạy `make contracts`"


def test_artefact_khop_nguon():
    """Sửa actions.py mà quên `make contracts` ⇒ đỏ ở đây, không phải ở repo FE
    ba ngày sau."""
    trong_file = set(json.loads(ACTIONS_JSON.read_text(encoding="utf-8"))["actions"])

    assert trong_file == set(ALL_ACTIONS)


def test_artefact_dung_byte_ma_script_sinh_ra():
    """Khớp tập hợp là chưa đủ: repo FE copy BYTE-FOR-BYTE, nên thụt lề hay thứ tự
    lệch cũng làm `diff` giữa hai repo kêu, dù nội dung ngữ nghĩa như nhau.

    Neo lại đúng đầu ra của script để artefact chỉ có một dạng hợp lệ.
    """
    assert ACTIONS_JSON.read_text(encoding="utf-8") == noi_dung_actions()


def test_dem_15_truoc_khi_so():
    """Đếm TRƯỚC khi so tập: tập rỗng so tập rỗng thì bằng nhau. Không có phép đếm
    này thì một script sinh hỏng (ghi `{"actions": []}`) làm cổng xanh vĩnh viễn.

    13 → 14 (2026-08-20, `0945_billing_action`): `billing.read` là action ĐẦU
    TIÊN nằm ngoài 13 nhóm gốc của PQ_01 §3.1 — Usage & Billing chưa tồn tại
    lúc spec đó viết.
    14 → 15 (2026-08-25, `0956_audit_action`): `audit.read`, màn Nhật ký."""
    assert len(json.loads(ACTIONS_JSON.read_text(encoding="utf-8"))["actions"]) == 17


# ─── audit-actions.json — sổ mã hành động nhật ký, cùng cơ chế với actions.json ──


def test_audit_artefact_ton_tai():
    assert AUDIT_JSON.exists(), "thiếu contracts/audit-actions.json — chạy `make contracts`"


def test_audit_artefact_khop_nguon():
    """So với `MA_TAT_CA` (mã sống ∪ mã đã nghỉ hưu) — artefact là thứ FE dùng để
    dịch nhãn cho CẢ lịch sử, không chỉ mã đang ghi hôm nay (xem `MA_DA_NGHI_HUU`)."""
    trong_file = set(json.loads(AUDIT_JSON.read_text(encoding="utf-8"))["actions"])
    assert trong_file == set(MA_TAT_CA)


def test_audit_artefact_dung_byte_ma_script_sinh_ra():
    assert AUDIT_JSON.read_text(encoding="utf-8") == noi_dung_audit_actions()


def test_audit_dem_truoc_khi_so():
    """Sàn 40 chứ không phải con số chính xác: sổ này mọc theo điểm ghi (khác
    `actions.json` cố định 15). Đếm để bắt artefact rỗng."""
    assert len(json.loads(AUDIT_JSON.read_text(encoding="utf-8"))["actions"]) >= 40


# ─── tools.json — 11 kỹ năng, cùng cơ chế với actions.json ───────────────────
#
# Vì sao 10 kỹ năng cũng phải là artefact chứ không để FE tự khai: màn Agent
# Studio hiện toggle theo tên nghiệp vụ và cảnh báo phụ thuộc, còn `RULES.md`
# sinh danh mục từ cùng danh sách đó. Hai bản chép tay là hai bản sẽ lệch — và
# lệch ở đây nghĩa là UI tắt một kỹ năng mà prompt vẫn dạy gọi, đúng lỗi AG_01
# §6 đang bắt sửa.

TOOLS_JSON = CONTRACTS / "tools.json"


def test_tools_artefact_ton_tai():
    assert TOOLS_JSON.exists(), "thiếu contracts/tools.json — chạy `make contracts`"


def test_tools_artefact_dung_byte_ma_script_sinh_ra():
    from scripts.gen_contracts import noi_dung_tools

    assert TOOLS_JSON.read_text(encoding="utf-8") == noi_dung_tools()


def test_dem_11_ky_nang_truoc_khi_so():
    """Đếm TRƯỚC khi so — cùng lý do như 13 nhóm hành động ở trên."""
    assert len(json.loads(TOOLS_JSON.read_text(encoding="utf-8"))["tools"]) == 11


def test_tools_artefact_khop_nguon():
    from portal.modules.config.tools import MUOI_HAI_KY_NANG, PHU_THUOC

    d = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))

    assert [t["ten"] for t in d["tools"]] == [k.ten for k in MUOI_HAI_KY_NANG]
    assert {t["ten"]: t["nhan"] for t in d["tools"]} == {k.ten: k.nhan for k in MUOI_HAI_KY_NANG}
    assert d["phuThuoc"] == {k: list(v) for k, v in PHU_THUOC.items()}


def test_moi_ky_nang_co_nhan_va_mo_ta():
    """Toggle không nhãn là toggle hiện tên hàm cho trưởng phòng kinh doanh —
    AG_01 §II.3 cấm đúng điều đó."""
    for t in json.loads(TOOLS_JSON.read_text(encoding="utf-8"))["tools"]:
        assert t["nhan"] and t["moTa"], t["ten"]


def test_phu_thuoc_chi_tro_toi_ky_nang_co_that():
    """Một phụ thuộc trỏ tới tên gõ sai là một cảnh báo không bao giờ hiện, và
    một validate BE không bao giờ chặn."""
    d = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))
    ten = {t["ten"] for t in d["tools"]}

    for goc, can in d["phuThuoc"].items():
        assert goc in ten, goc
        assert set(can) <= ten, can
