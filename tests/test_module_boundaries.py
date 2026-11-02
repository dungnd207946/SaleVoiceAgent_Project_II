"""Cấm import chéo ruột module — cưỡng chế bằng AST, không phải bằng quy ước.

LUẬT: portal.modules.<a> chỉ được import
  - portal.core.*
  - portal.modules.<b>.contracts   (mặt tiền — DTO + Protocol, không logic)
Import portal.modules.<b>.service / .repo / .router là LỖI.

Vì sao cưỡng chế: yêu cầu "xây module này không ảnh hưởng module khác" chỉ thật
khi có thứ chặn. Một import chéo lọt qua review là hai module dính nhau âm thầm,
và người nhận module sau sẽ không biết mình vừa phá cái gì.

Ở M1 chưa có module nào — hai test công khai (test_khong_module_nao_...,
test_module_nao_cung_co_file_contracts) return sớm và không thể đỏ, vì
MODULES_DIR chưa tồn tại. Một cổng không bao giờ đỏ được thì không phải là cổng
— nó là trang trí. Vì vậy logic quét được tách ra hai hàm thuần
(_vi_pham_import_cheo, _module_thieu_contracts) nhận một Path bất kỳ, và bốn
test synthetic bên dưới chạy chúng trên một cây module GIẢ dựng bằng tmp_path
để chứng minh: (1) một import ruột bị bắt kèm đúng tên file + tên import trong
thông điệp, (2) import qua contracts.py và import trong-cùng-module KHÔNG bị
báo sai, (3) module thiếu contracts.py bị bắt. Khi module thật đầu tiên
(M2a) xuất hiện, hai test công khai sẽ tự động thoát khỏi nhánh return-sớm và
bắt đầu quét cây thật — không cần sửa file này.
"""

import ast
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent
MODULES_DIR = GOC / "src" / "portal" / "modules"
SCRIPTS_DIR = GOC / "scripts"
CHO_PHEP_DUOI = "contracts"


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _vi_pham_import_cheo(modules_dir: Path) -> list[str]:
    """Hàm thuần: quét cây module dưới `modules_dir`, trả về danh sách vi phạm.

    Tách khỏi test để dùng chung cho cây thật (MODULES_DIR, chưa tồn tại ở M1)
    và cây giả dựng trong test (tmp_path) — chỉ nhờ vậy logic mới có test đỏ
    được ngay hôm nay, thay vì phải đợi module đầu tiên ra đời.
    """
    vi_pham: list[str] = []
    for py in sorted(modules_dir.rglob("*.py")):
        rel = py.relative_to(modules_dir)
        chu_so_huu = rel.parts[0]
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for name in _imported_names(tree):
            if not name.startswith("portal.modules."):
                continue
            phan = name.split(".")
            if len(phan) < 3:
                continue
            bi_import = phan[2]
            if bi_import == chu_so_huu:
                continue  # trong cùng module — bình thường
            if len(phan) >= 4 and phan[3] == CHO_PHEP_DUOI:
                continue  # qua mặt tiền — hợp lệ
            vi_pham.append(f"{rel}: import {name}")
    return vi_pham


def _module_thieu_contracts(modules_dir: Path) -> list[str]:
    """Hàm thuần: trả về tên các thư mục module (không phải `_`-prefixed)
    dưới `modules_dir` mà không có `contracts.py` — cùng lý do tách hàm ở trên."""
    return [
        d.name
        for d in sorted(modules_dir.iterdir())
        if d.is_dir() and not d.name.startswith("_") and not (d / "contracts.py").exists()
    ]


def test_khong_module_nao_import_ruot_module_khac():
    """Chạy trên cây MODULES_DIR thật.

    Return sớm là ĐÚNG ở M1 — chưa có module nào để quét (portal/modules/ chưa
    tồn tại; M2a là module đầu tiên tạo nó). Bản thân logic quét đã được chứng
    minh bắt được vi phạm bởi các test synthetic bên dưới, nên early-return ở
    đây không phải là một cổng rỗng — nó chỉ đơn giản là "chưa có gì để quét".
    """
    if not MODULES_DIR.exists():
        return  # chưa có module nào — đúng ở M1

    vi_pham = _vi_pham_import_cheo(MODULES_DIR)
    assert not vi_pham, "Import chéo ruột module. Chỉ được import portal.modules.<khác>.contracts:\n" + "\n".join(
        vi_pham
    )


def test_module_nao_cung_co_file_contracts():
    """contracts.py là file duy nhất module khác được đọc. Không có nó thì
    module này không giao tiếp được, và người khác sẽ đi đường tắt.

    Return sớm là ĐÚNG ở M1 — cùng lý do trên; logic đã được chứng minh bởi
    test_helper_bat_duoc_module_thieu_contracts bên dưới.
    """
    if not MODULES_DIR.exists():
        return
    thieu = _module_thieu_contracts(MODULES_DIR)
    assert thieu == [], f"module thiếu contracts.py: {thieu}"


# ─── Mặt tiền cũng áp cho `scripts/` ────────────────────────────────────────


def _import_ruot_realestate(py: Path) -> list[str]:
    """Tên import chọc thẳng vào ruột `portal.modules.realestate` trong MỘT file.

    Tách riêng khỏi `_vi_pham_import_cheo` vì hai bộ quét trả lời hai câu khác
    nhau: cái kia hỏi "module A có chọc vào ruột module B không" (`chu_so_huu`
    suy từ đường dẫn), còn `scripts/` không THUỘC module nào — nó là người ngoài
    với mọi module, nên không có `chu_so_huu` để miễn trừ.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    xau: list[str] = []
    for name in _imported_names(tree):
        phan = name.split(".")
        if phan[:3] != ["portal", "modules", "realestate"]:
            continue
        if len(phan) >= 4 and phan[3] != CHO_PHEP_DUOI:
            xau.append(name)
    return xau


def test_seed_bds_import_qua_mat_tien_khong_choc_vao_ruot():
    """`tests/test_module_boundaries.py` chỉ quét `src/portal/modules`, nên luật
    mặt tiền không được cưỡng chế ngoài `src/` — và `scripts/seed_bds.py` đã
    trôi qua khe đó, import thẳng `portal.modules.realestate.chinh_sach` dù
    `contracts.py` re-export đúng những tên ấy.

    Cổng này khoanh vào ĐÚNG `seed_bds.py`, không quét cả `scripts/`, vì hai
    script của module khác (`gen_contracts.py` → `modules.config.tools`,
    `agent_gia.py` → `modules.config.bundle`) đang vi phạm cùng luật. Sửa chúng
    là sửa script của module khác trong một đợt sửa của M4a — nên chúng được
    BÁO CÁO, không bị sửa lén ở đây. Mở rộng cổng ra cả `scripts/` là việc làm
    được ngay sau khi hai script đó có mặt tiền để đi qua.
    """
    xau = _import_ruot_realestate(SCRIPTS_DIR / "seed_bds.py")
    assert not xau, (
        f"seed_bds.py chọc thẳng vào ruột module realestate: {xau}. "
        "Import từ portal.modules.realestate.contracts — mặt tiền đã re-export đủ."
    )


def test_helper_bat_duoc_import_ruot_tren_file_gia(tmp_path):
    """Canh chính bộ quét: nếu `_import_ruot_realestate` hỏng thì test trên xanh
    vì nó quét 0 import — một cổng luôn xanh là một cổng đã chết."""
    xau = tmp_path / "xau.py"
    xau.write_text("from portal.modules.realestate.repo import ghi_can\n")
    assert _import_ruot_realestate(xau) == ["portal.modules.realestate.repo"]

    tot = tmp_path / "tot.py"
    tot.write_text("from portal.modules.realestate.contracts import COT_UNIT\nimport os\n")
    assert _import_ruot_realestate(tot) == []


def test_helper_bat_duoc_import_cheo_tren_cay_gia(tmp_path):
    """Chứng minh _vi_pham_import_cheo THẬT SỰ bắt được vi phạm, trên cây giả.

    m_a/service.py import thẳng vào m_b.repo (ruột) — phải bị báo, kèm đúng
    tên file và đúng tên import trong thông điệp, để người đọc log sửa được
    ngay không cần đoán.
    """
    m_a = tmp_path / "m_a"
    m_a.mkdir()
    (m_a / "__init__.py").write_text("")
    (m_a / "service.py").write_text("from portal.modules.m_b.repo import X\n")

    m_b = tmp_path / "m_b"
    m_b.mkdir()
    (m_b / "__init__.py").write_text("")
    (m_b / "contracts.py").write_text("class X: ...\n")

    vi_pham = _vi_pham_import_cheo(tmp_path)

    assert len(vi_pham) == 1
    (thong_diep,) = vi_pham
    assert "service.py" in thong_diep
    assert "portal.modules.m_b.repo" in thong_diep


def test_helper_khong_bao_sai_import_hop_le(tmp_path):
    """Chứng minh import hợp lệ (qua contracts.py, hoặc trong cùng module)
    KHÔNG bị báo — nếu không thì cổng này sẽ chặn cả code đúng."""
    m_a = tmp_path / "m_a"
    m_a.mkdir()
    (m_a / "__init__.py").write_text("")
    (m_a / "repo.py").write_text("class Z: ...\n")
    (m_a / "service.py").write_text(
        "from portal.modules.m_b.contracts import Y\nfrom portal.modules.m_a.repo import Z\n"
    )

    m_b = tmp_path / "m_b"
    m_b.mkdir()
    (m_b / "__init__.py").write_text("")
    (m_b / "contracts.py").write_text("class Y: ...\n")

    assert _vi_pham_import_cheo(tmp_path) == []


def test_helper_bat_duoc_module_thieu_contracts(tmp_path):
    """Chứng minh _module_thieu_contracts THẬT SỰ bắt module thiếu mặt tiền,
    trên cây giả — m_a không có contracts.py, m_b có."""
    m_a = tmp_path / "m_a"
    m_a.mkdir()
    (m_a / "__init__.py").write_text("")
    (m_a / "service.py").write_text("")

    m_b = tmp_path / "m_b"
    m_b.mkdir()
    (m_b / "__init__.py").write_text("")
    (m_b / "contracts.py").write_text("")

    assert _module_thieu_contracts(tmp_path) == ["m_a"]
