"""Luật ranh giới: `modules/<m>` chỉ import `portal.core`, `portal.api` và chính nó.

Logic hai module cùng cần thì đưa lên `core/` (vd `core/ban_hang.py`), không import ruột
nhau — import chéo là cách hai module âm thầm dính thành một. Đọc AST, không cần DB.
"""

import ast
from pathlib import Path

MODULES = Path(__file__).resolve().parent.parent / "src" / "portal" / "modules"


def _vi_pham() -> list[str]:
    ra: list[str] = []
    for tep in MODULES.rglob("*.py"):
        cua = tep.relative_to(MODULES).parts[0]
        for nut in ast.walk(ast.parse(tep.read_text(encoding="utf-8"))):
            ten = nut.module if isinstance(nut, ast.ImportFrom) else None
            ds = [ten] if ten else [a.name for a in nut.names] if isinstance(nut, ast.Import) else []
            for t in ds:
                if t and t.startswith("portal.modules.") and t.split(".")[2] != cua:
                    ra.append(f"{tep.relative_to(MODULES)}:{nut.lineno} import {t}")
    return ra


def test_module_khong_import_ruot_nhau() -> None:
    assert _vi_pham() == []
