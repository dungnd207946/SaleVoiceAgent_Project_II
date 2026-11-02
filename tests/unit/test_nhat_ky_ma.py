"""Sổ mã hành động nhật ký (`core/nhat_ky_ma.py`) phải KHỚP các literal ở điểm ghi.

Vì sao có sổ: ~50 mã là chuỗi literal rải ở 50 điểm ghi, hai lối đặt tên
(`thanh_vien.go` vs `realestate.project.update`). FE cần một danh sách để dịch ra
tiếng Việt; artefact `contracts/audit-actions.json` sinh từ sổ này. Sổ mà lệch
điểm ghi thì FE hiện mã thô — và không ai bị nhắc. Cổng này là cái nhắc.

Cổng canh LITERAL: mã truyền qua biến (`HANH_DONG` của ingest, `hanh_dong` đi qua
service) thì bỏ qua — chiều ngược (mọi mã trong sổ phải có mặt dạng `"<mã>"` ở
đâu đó trong src) đỡ cho ca đó.
"""

import ast
import re
from pathlib import Path

from portal.core import nhat_ky_ma
from portal.core.nhat_ky_ma import MA_DA_NGHI_HUU, MA_HANH_DONG, MA_TAT_CA

GOC = Path(__file__).resolve().parents[2] / "src" / "portal"
_TEP_SO = Path(nhat_ky_ma.__file__).resolve()

_VI_TRI_HANH_DONG = {"ghi": 2, "ghi_he_thong": 1, "_nhat_ky": 2}
"""Chỉ số đối số VỊ TRÍ mang `hanh_dong`: `nhat_ky.ghi(conn, tenant_id, hanh_dong, …)`,
`nhat_ky.ghi_he_thong(conn, hanh_dong, …)`, `_nhat_ky(conn, p, hanh_dong, …)` (realestate)."""


def _ten_goi(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "nhat_ky":
        return f.attr if f.attr in _VI_TRI_HANH_DONG else None
    if isinstance(f, ast.Name) and f.id == "_nhat_ky":
        return "_nhat_ky"
    return None


def _ma_literal(call: ast.Call, ten: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == "hanh_dong":
            v = kw.value
            return v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else None
    i = _VI_TRI_HANH_DONG[ten]
    if len(call.args) > i:
        a = call.args[i]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return None


def _quet() -> list[tuple[str, str]]:
    """[(đường dẫn tương đối, mã)] cho MỌI điểm ghi có mã literal."""
    ra: list[tuple[str, str]] = []
    for tep in sorted(GOC.rglob("*.py")):
        for n in ast.walk(ast.parse(tep.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            ten = _ten_goi(n)
            if ten is None:
                continue
            ma = _ma_literal(n, ten)
            if ma is not None:
                ra.append((str(tep.relative_to(GOC)), ma))
    return ra


def test_moi_literal_o_diem_ghi_deu_co_trong_so() -> None:
    thieu = sorted({(tep, ma) for tep, ma in _quet() if ma not in MA_HANH_DONG})
    assert not thieu, f"mã ở điểm ghi chưa có trong core/nhat_ky_ma.py: {thieu}"


def test_so_khong_co_ma_chet() -> None:
    """Mã trong sổ phải xuất hiện dạng literal `"<mã>"` ở đâu đó trong src — kể cả
    khi điểm ghi truyền qua biến (`HANH_DONG = "ingest.tenant_im_lang"`).

    LOẠI chính `core/nhat_ky_ma.py` khỏi văn bản quét: nếu không, dòng khai báo
    của MỌI mã (kể cả một mã bịa hoàn toàn, chưa từng có điểm ghi thật) tự khớp
    `f'"{ma}"'` với chính nó trong file này — cổng không thể đỏ cho bất kỳ mã
    nào, dù mã đó chưa từng được ghi ở đâu ngoài chính sổ. Loại file này ra thì
    cổng chỉ còn tin vào điểm ghi THẬT nằm ở nơi khác."""
    van_ban = "\n".join(p.read_text(encoding="utf-8") for p in GOC.rglob("*.py") if p.resolve() != _TEP_SO)
    chet = sorted(ma for ma in MA_HANH_DONG if f'"{ma}"' not in van_ban)
    assert not chet, f"mã trong sổ không còn điểm ghi nào: {chet}"


def test_bo_quet_con_song() -> None:
    """Đổi tên `nhat_ky`/`_nhat_ky` hay đổi thứ tự tham số là bộ quét thấy 0 điểm
    ghi và test trên xanh vĩnh viễn. Neo một sàn."""
    assert len(_quet()) >= 40, f"chỉ quét được {len(_quet())} điểm ghi — bộ quét hỏng?"


def test_dang_ma() -> None:
    """`<nhóm>.<việc>[.<việc>]` chữ thường — `split_part(hanh_dong, '.', 1)` ở repo
    audit và `NHOM_LOC` bên FE dựa vào dạng này. Áp cho `MA_TAT_CA`: mã nghỉ hưu
    cũng phải đúng dạng, FE dịch nhãn cho cả hai tập bằng cùng một quy tắc."""
    sai = sorted(ma for ma in MA_TAT_CA if not re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", ma))
    assert not sai, sai


def test_hai_tap_roi_nhau() -> None:
    """`MA_HANH_DONG` (sống) và `MA_DA_NGHI_HUU` (nghỉ hưu) không được chung mã —
    một mã vừa "còn điểm ghi" vừa "đã nghỉ hưu" là mâu thuẫn ngay trong định nghĩa,
    và sẽ làm `MA_TAT_CA` không nói lên gì (hợp của hai tập chồng nhau)."""
    assert not (MA_HANH_DONG & MA_DA_NGHI_HUU)


def test_ma_nghi_huu_khong_con_diem_ghi() -> None:
    """Mã đã CHUYỂN xuống `MA_DA_NGHI_HUU` phải thật sự hết điểm ghi — nếu một mã
    còn xuất hiện dạng literal `"<mã>"` ở đâu đó trong `src/portal` NGOÀI chính
    `core/nhat_ky_ma.py`, nó đang được ghi tiếp, tức phải nằm ở `MA_HANH_DONG`
    (tập sống), không phải tập nghỉ hưu — chuyển nhầm chiều là giấu một điểm ghi
    đang chạy khỏi cổng `test_moi_literal_o_diem_ghi_deu_co_trong_so` phía trên."""
    van_ban = "\n".join(p.read_text(encoding="utf-8") for p in GOC.rglob("*.py") if p.resolve() != _TEP_SO)
    con_song = sorted(ma for ma in MA_DA_NGHI_HUU if f'"{ma}"' in van_ban)
    assert not con_song, f"mã nghỉ hưu còn điểm ghi thật, phải chuyển về MA_HANH_DONG: {con_song}"
