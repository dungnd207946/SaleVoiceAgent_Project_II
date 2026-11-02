"""Migration nào đọc/ghi DỮ LIỆU trong `tenant_data` phải tự gỡ FORCE RLS.

`control.enforce_tenant_isolation` bật `FORCE ROW LEVEL SECURITY`, và FORCE có mặt đúng để
RLS áp CẢ cho chủ bảng (header `0003`). Migration chạy bằng `portal_migrator` và không set
`app.tenant_id`, nên mọi câu backfill của nó thấy **0 hàng** — trên môi trường thật, nơi
migrator là owner-KHÔNG-superuser. Ở testcontainer thì `POSTGRES_USER=portal_migrator` chính
là bootstrap superuser, mà superuser bỏ qua RLS bất kể FORCE, nên **không test nào chạy DB
bắt được lớp lỗi này** — đó là lý do cổng này là cổng TĨNH.

Ba lần đã sập, hai trong số đó im lặng:

  · `0920` backfill `project_code` chạm 0 hàng, báo thành công. Chỉ báo tab kiến thức mù
    với mọi hàng cũ. Không ai biết cho tới hôm nay (`0933` dựng lại).
  · `0927` di trú csbh chép 0 hàng rồi xoá 0 hàng, sau đó `ADD CONSTRAINT` nổ trên đúng
    những hàng vừa "xoá" — chết ở stage deploy, thông báo không nhắc gì tới RLS.
  · `0931` xoá hàng chưa chiếu: xoá 0 hàng rồi DROP luôn cột phân biệt.

Cổng đọc **hằng chuỗi trong thân `upgrade()`** chứ không đọc cả tệp: comment `#` không tính
là bằng chứng. `0920` có hẳn một comment khẳng định "owner nên không bị RLS" — nếu cổng đọc
cả tệp thì chính lời khẳng định sai đó sẽ làm nó xanh.
"""

import ast
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"

# `JOIN`/`USING` cũng đọc dữ liệu và cũng bị RLS lọc — không có chữ `FROM tenant_data.` nào.
_DML = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|JOIN|USING)\s+tenant_data\.", re.I)
_VIEW = re.compile(r"CREATE\s+(OR\s+REPLACE\s+)?VIEW", re.I)
# Chỉ `NO FORCE`, không đòi trọn `NO FORCE ROW LEVEL SECURITY`: câu này hay được dựng bằng
# f-string (`{'FORCE' if bat else 'NO FORCE'} ROW LEVEL SECURITY`) nên các mảnh literal không
# còn kề nhau. Trong một migration thì hai chữ đó không có nghĩa nào khác.
_GO = re.compile(r"NO\s+FORCE\b|app\.tenant_id", re.I)

# Đã áp trên môi trường thật trước khi biết bẫy — sửa tại chỗ vô nghĩa (alembic không chạy
# lại), phải là migration mới. Thêm tên vào đây thì phải kèm migration dựng lại backfill.
MIEN_TRU = {"0920_kb_state_skipped_va_project_code.py": "0933_nap_lai_project_code_kb_state.py"}


def _cau(goc: ast.AST) -> list[str]:
    """Mỗi hằng chuỗi / f-string thành MỘT câu.

    Nối các mảnh literal của f-string lại thay vì coi mỗi mảnh là một câu: chỗ nội suy cắt
    `CREATE VIEW …` khỏi `FROM tenant_data.…` nằm ngay dưới nó, và hai mảnh rời thì luật
    "bỏ qua view" không còn chỗ bám.
    """
    ra, trong_fstring = [], set()
    for n in ast.walk(goc):
        if isinstance(n, ast.JoinedStr):
            manh = [c for c in ast.walk(n) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            trong_fstring |= set(map(id, manh))
            ra.append(" ".join(c.value for c in manh))
    for n in ast.walk(goc):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in trong_fstring:
            ra.append(n.value)
    return ra


def _ham(tep: Path, ten: str) -> ast.FunctionDef | None:
    cay = ast.parse(tep.read_text())
    return next((n for n in cay.body if isinstance(n, ast.FunctionDef) and n.name == ten), None)


def test_backfill_tenant_data_deu_go_force_rls():
    thieu = []
    for tep in sorted(VERSIONS.glob("*.py")):
        up = _ham(tep, "upgrade")
        if up is None:
            continue
        if not any(_DML.search(s) and not _VIEW.search(s) for s in _cau(up)):
            continue
        # Bằng chứng phải nằm trên ĐƯỜNG ĐI của `upgrade()`: trong thân nó, hoặc trong một
        # hàm phụ mà nó gọi (`_force_rls`). Quét cả tệp thì một NO FORCE chỉ có ở
        # `downgrade()` cũng làm cổng xanh.
        goi = {n.func.id for n in ast.walk(up) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        bang_chung = _cau(up) + [s for ten in goi if (h := _ham(tep, ten)) for s in _cau(h)]
        if not any(_GO.search(s) for s in bang_chung) and tep.name not in MIEN_TRU:
            thieu.append(tep.name)

    assert not thieu, (
        f"{thieu} đọc/ghi dữ liệu trong tenant_data mà không gỡ FORCE RLS ⇒ chạm 0 hàng "
        "trên môi trường thật và BÁO THÀNH CÔNG. Bọc đoạn đó bằng "
        "`ALTER TABLE … NO FORCE ROW LEVEL SECURITY` → backfill → `… FORCE …`, hoặc "
        "`SET LOCAL app.tenant_id` cho từng tenant (header 0003)."
    )


def test_mien_tru_deu_co_migration_dung_lai():
    """Miễn trừ chỉ hợp lệ khi backfill hỏng đã được một migration khác dựng lại."""
    for tep, dung_lai in MIEN_TRU.items():
        assert (VERSIONS / tep).exists(), f"{tep} không còn — bỏ nó khỏi MIEN_TRU"
        assert (VERSIONS / dung_lai).exists(), f"{tep} được miễn trừ nhưng {dung_lai} không tồn tại"


def test_regex_bat_ca_cac_menh_de_doc_du_lieu():
    """Cổng đứng trên regex này, nên chính nó phải có bài kiểm. `JOIN tenant_data.…` từng lọt:
    một backfill JOIN sang bảng tenant để lấy khoá vẫn bị RLS lọc y như `FROM`."""
    lot = [
        "UPDATE tenant_data.kb_index_state SET x = 1",
        "INSERT INTO tenant_data.media (a) VALUES (1)",
        "DELETE FROM tenant_data.documents WHERE id = 1",
        "SELECT 1 FROM tenant_data.projects",
        "SELECT 1 FROM control.jobs j JOIN tenant_data.projects p ON p.id = j.rid",
        "DELETE FROM control.jobs USING tenant_data.media m WHERE m.id = 1",
    ]
    for sql in lot:
        assert _DML.search(sql), f"cổng bỏ sót: {sql}"

    assert not _DML.search("ALTER TABLE tenant_data.media ADD COLUMN x text"), "DDL không phải backfill"
    assert not _DML.search("CREATE INDEX i ON tenant_data.media (id)"), "DDL không phải backfill"
