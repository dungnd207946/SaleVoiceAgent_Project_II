"""Gói `src/portal` import THẲNG phải được khai trong `[project].dependencies`.

Dep bắc cầu là hợp đồng của gói KHÁC, không phải của repo này: `pypdfium2` vào được
nhờ docling, và ngày docling đổi backend PDF thì `import pypdfium2` nổ lúc CHẠY, ở
production, không lộ ở CI của người đổi. Đúng cách `minio` từng hỏng — hai comment
trong `pyproject.toml` đã cảnh báo, nhưng không cổng nào đo.
"""

import ast
import pathlib
import re
import sys
import tomllib
from importlib.metadata import packages_distributions

GOC = pathlib.Path(__file__).resolve().parents[2]

# Nợ có chủ đích, KHÔNG phải danh sách để thêm vào cho tiện:
#   pydantic  — API công khai của `fastapi`/`pydantic-settings`, hai gói đã khai; phiên
#               bản do chúng ghim, khai lại là mở một chỗ để hai bản lệch nhau.
#   botocore  — chỉ dùng để bắt `ClientError` của `aioboto3` (đã khai); ngoại lệ của một
#               client là API của chính client đó.
# Gỡ một mục ở đây phải kèm một dòng trong `[project].dependencies`.
NO_CO_CHU_DICH = {"pydantic", "botocore"}


def _ten_goi_import_thang() -> set[str]:
    ten: set[str] = set()
    for tep in (GOC / "src" / "portal").rglob("*.py"):
        for nut in ast.walk(ast.parse(tep.read_text(encoding="utf-8"))):
            if isinstance(nut, ast.Import):
                ten.update(a.name.split(".")[0] for a in nut.names)
            elif isinstance(nut, ast.ImportFrom) and nut.level == 0 and nut.module:
                ten.add(nut.module.split(".")[0])
    return ten - set(sys.stdlib_module_names) - {"portal"}


def _ten_phan_phoi(ds: list[str]) -> set[str]:
    # `docling-slim[a,b]>=2.119` → `docling-slim`; tên phân phối chuẩn hoá về gạch ngang.
    return {re.split(r"[><=!~\[ ]", d)[0].lower().replace("_", "-") for d in ds}


def _da_khai() -> set[str]:
    cfg = tomllib.loads((GOC / "pyproject.toml").read_text(encoding="utf-8"))
    return _ten_phan_phoi(cfg["project"]["dependencies"])


def test_moi_goi_import_thang_deu_khai_trong_pyproject():
    khai = _da_khai()
    phan_phoi = packages_distributions()

    thieu = []
    for ten in sorted(_ten_goi_import_thang() - NO_CO_CHU_DICH):
        # Tên import khác tên phân phối rất thường: `yaml`→PyYAML, `docling`→docling-slim.
        ds = [d.lower().replace("_", "-") for d in phan_phoi.get(ten, [])]
        if not ds:
            thieu.append(f"{ten} (không rõ gói phân phối — chưa cài?)")
        elif not any(d in khai for d in ds):
            thieu.append(f"{ten} → {ds}")

    assert thieu == [], "import thẳng nhưng chỉ vào được nhờ dep bắc cầu:\n  " + "\n  ".join(thieu)
