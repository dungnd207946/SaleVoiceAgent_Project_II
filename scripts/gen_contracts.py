"""Sinh `contracts/` từ nguồn trong `src/portal` — chạy bằng `make contracts`.

Vì sao có bước sinh thay vì viết tay: `contracts/actions.json` là thứ repo
frontend copy về để canh cổng parity. Một artefact viết tay thì sai lệch so với
nguồn là chuyện bình thường; một artefact sinh ra thì sai lệch là **test đỏ**
(`tests/api/test_contracts.py`).

Script này KHÔNG ghi sang repo frontend — nó không biết repo đó nằm ở đâu, và một
script tự ghi ra ngoài cây của mình là thứ khó lần khi đi sai. Việc copy là một
dòng tường minh, xem contracts/README.md.
"""

import json
from pathlib import Path

from portal.core.auth.actions import ALL_ACTIONS
from portal.core.nhat_ky_ma import MA_TAT_CA
from portal.modules.config.tools import MUOI_HAI_KY_NANG, PHU_THUOC

GOC = Path(__file__).resolve().parent.parent
CONTRACTS = GOC / "contracts"


def noi_dung_actions() -> str:
    """JSON của 13 nhóm hành động. Sắp theo alphabet để diff giữa hai lần sinh chỉ
    hiện thay đổi thật, không hiện thứ tự đổi ngẫu nhiên (frozenset không có thứ tự)."""
    return json.dumps({"actions": sorted(ALL_ACTIONS)}, indent=2, ensure_ascii=False) + "\n"


def noi_dung_audit_actions() -> str:
    """JSON sổ mã hành động của `control.audit_log` — FE dịch nhãn từ đây
    (`features/platform/so-hanh-dong.ts`, cổng `tests/audit-actions-parity.test.ts`).
    Sắp alphabet, cùng lý do `actions.json`.

    Nguồn là `MA_TAT_CA` (`MA_HANH_DONG` ∪ `MA_DA_NGHI_HUU`), KHÔNG chỉ mã đang
    ghi hôm nay — mã đã nghỉ hưu vẫn còn hàng trong `control.audit_log`
    (bảng chỉ ghi thêm) nên FE vẫn cần dịch được nhãn cho lịch sử."""
    return json.dumps({"actions": sorted(MA_TAT_CA)}, indent=2, ensure_ascii=False) + "\n"


def noi_dung_tools() -> str:
    """JSON của 13 kỹ năng + bảng phụ thuộc, cho màn Agent Studio.

    GIỮ THỨ TỰ khai báo, không sắp alphabet như `actions.json`: thứ tự trong
    `MUOI_HAI_KY_NANG` là thứ tự nghiệp vụ (nhận diện dự án -> giới thiệu -> tra
    thông tin -> chốt lịch), và đó là thứ tự toggle hiện trên màn hình. Sắp lại
    theo alphabet là làm danh sách khó đọc để đổi lấy một diff ổn định mà thứ tự
    khai báo vốn đã ổn định.

    `moTa` đi kèm dù FE không hiện nó: nó là thứ vào `RULES.md`, và có nó trong
    artefact nghĩa là người sửa nhãn ở FE thấy luôn câu mà LLM đang đọc.
    """
    d = {
        "tools": [{"ten": k.ten, "nhan": k.nhan, "moTa": k.mo_ta} for k in MUOI_HAI_KY_NANG],
        "phuThuoc": {k: list(v) for k, v in sorted(PHU_THUOC.items())},
    }
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    CONTRACTS.mkdir(exist_ok=True)
    dich = CONTRACTS / "actions.json"
    dich.write_text(noi_dung_actions(), encoding="utf-8")
    print(f"đã sinh {dich.relative_to(GOC)} — {len(ALL_ACTIONS)} nhóm hành động")

    dich_audit = CONTRACTS / "audit-actions.json"
    dich_audit.write_text(noi_dung_audit_actions(), encoding="utf-8")
    print(f"đã ghi {dich_audit}")

    dich_tools = CONTRACTS / "tools.json"
    dich_tools.write_text(noi_dung_tools(), encoding="utf-8")
    print(f"đã sinh {dich_tools.relative_to(GOC)} — {len(MUOI_HAI_KY_NANG)} kỹ năng")

    print("nhớ copy sang repo frontend: xem contracts/README.md")


if __name__ == "__main__":
    main()
