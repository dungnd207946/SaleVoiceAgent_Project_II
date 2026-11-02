"""CỔNG 11 (spec §9) — quét động. BR13.

Bắt được người thêm một endpoint ghi mà quên `_nhat_ky()`. Review không bắt được
vì endpoint mới trông đúng: nó có `require(action)`, có `tenant_conn()`, có test
riêng — chỉ thiếu một dòng mà không test nào của nó quan tâm.
"""

import ast
import inspect
from pathlib import Path

MIEN_TRU: frozenset[str] = frozenset()
"""Route ghi được miễn ghi nhật ký. RỖNG có chủ ý — thêm tên vào đây phải kèm
một câu giải thích, và câu đó sẽ bị đọc lại ở mọi lần review sau."""


def _cay_router() -> ast.Module:
    from portal.modules.realestate import router

    return ast.parse(Path(inspect.getfile(router)).read_text(encoding="utf-8"))


def _la_route_ghi(fn: ast.AsyncFunctionDef) -> str:
    """Trả method HTTP nếu hàm là route POST/PATCH/DELETE, ngược lại ''."""
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
            continue
        if not (isinstance(d.func.value, ast.Name) and d.func.value.id == "ROUTER"):
            continue
        if d.func.attr in ("post", "patch", "delete", "put"):
            return d.func.attr
    return ""


def _co_goi_nhat_ky(fn: ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_nhat_ky" for n in ast.walk(fn)
    )


def test_moi_route_ghi_deu_ghi_nhat_ky():
    thieu = [
        fn.name
        for fn in ast.walk(_cay_router())
        if isinstance(fn, ast.AsyncFunctionDef)
        and _la_route_ghi(fn)
        and fn.name not in MIEN_TRU
        and not _co_goi_nhat_ky(fn)
    ]
    assert not thieu, (
        f"route ghi nhưng không vào nhật ký: {thieu}. BR13 — không ghi thì lúc "
        "một căn bị xoá nhầm, không ai lần được ai làm."
    )


def test_it_nhat_bay_route_ghi_duoc_quet():
    """Canh chính cái quét. Nếu `_la_route_ghi` hỏng (đổi tên `ROUTER`, đổi cách
    khai decorator) thì test trên xanh vì nó quét 0 route — một cổng luôn xanh
    là một cổng đã chết."""
    so = sum(1 for fn in ast.walk(_cay_router()) if isinstance(fn, ast.AsyncFunctionDef) and _la_route_ghi(fn))
    assert so >= 7, f"chỉ quét được {so} route ghi — bộ quét hỏng, không phải code hỏng"
