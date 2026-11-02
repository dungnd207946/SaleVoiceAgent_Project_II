"""Backfill tenant_data.project_hot_words cho project ĐÃ TỒN TẠI trước 0963

VÌ SAO LÀ MIGRATION, KHÔNG PHẢI SCRIPT CHẠY TAY: CI/CD chạy `alembic upgrade
head` TỰ ĐỘNG ở mọi lượt deploy — `.gitlab-ci.yml` gọi
`docker compose run --rm migrate` (entrypoint `migrate` = `alembic upgrade
head`) TRƯỚC KHI `serve`/`worker` lên, trên cả `develop` lẫn `prod`, không ai
đăng nhập vào máy gõ lệnh. Vì vậy bất cứ việc gì cần chạy ĐÚNG MỘT LẦN nhưng
KHÔNG được phép chờ người vận hành phải nằm ở đây, không phải ở `scripts/`
(nơi mọi thứ CHẠY TAY theo đúng quy ước sẵn có của repo — `backfill_public_url.py`,
`sinh_thumb_backfill.py`).

BẢN SAO ĐÔNG LẠNH của `realestate/hot_words.py::extract_hot_words` + hai file
`data/{vi_words,en_words}.txt`, tại đúng thời điểm viết migration này — Y
NGUYÊN lý do đã ghi ở `0104_vai_tro_dong.py:28-30`: **migration không được
import code ứng dụng** (`from portal.modules...`), vì nó phải chạy đúng bất kể
code ứng dụng sau này đổi ra sao (thuật toán tách từ đổi, wordlist cập nhật,
module bị dời chỗ...). Wordlist đông lạnh nằm ở
`migrations/versions/_data/0964_backfill_hot_words/` — MỘT BẢN SAO riêng,
KHÔNG phải cùng file với `src/portal/modules/realestate/data/`, dù nội dung
hôm nay giống hệt nhau. Sửa thuật toán/wordlist ở `hot_words.py` về sau KHÔNG
được sửa lại file này — nó là bản ghi lịch sử của một lần chạy, không phải
logic đang sống.

IDEMPOTENT: xoá-rồi-ghi đúng theo `project_id`, và `ON CONFLICT (tenant_id,
hot_word) DO NOTHING` — chạy lại (vd `alembic upgrade head` từ đầu trên một DB
mới toanh, disaster recovery, CI dựng lại DB) không hỏng gì, chỉ tốn công vô
ích tính lại đúng những gì đã đúng.

Bỏ qua row anchor hệ thống `project_code = '__ALL__'`
(`realestate/contracts.py::SENTINEL_TENANT`, chép tay hằng số vì lý do đã nêu
ở trên) — nó không phải project có tên thật, tách hot word từ nó là nhiễu vô
nghĩa.

`NO FORCE` / `FORCE` lại quanh backfill — đúng luật đã ghi ở
`0003_role_and_isolation_helper.py`: migration chạy bằng owner
(`portal_migrator`), và CẢ `tenant_data.projects` (FORCE từ `0913`) LẪN
`tenant_data.project_hot_words` (FORCE từ `0963`) đều lọc theo
`app.tenant_id` — không tắt tạm hai bảng này thì migration đọc/ghi ĐÚNG 0
HÀNG cho MỌI tenant, im lặng, không một lỗi nào báo.

Revision ID: 0964_backfill_hot_words
Revises: 0963_project_hot_words
"""

import re
import unicodedata
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0964_backfill_hot_words"
down_revision = "0963_project_hot_words"
branch_labels = None
depends_on = None

_THU_MUC_DU_LIEU = Path(__file__).parent / "_data" / "0964_backfill_hot_words"
_SENTINEL_TENANT = "__ALL__"  # chép tay `realestate/contracts.py::SENTINEL_TENANT` — xem docstring trên

_BANG_D = str.maketrans("đĐ", "dD")
_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _bo_dau(text: str) -> str:
    text = text.translate(_BANG_D)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text)


def _doc_tu_dien(ten_tep: str) -> frozenset[str]:
    duong_dan = _THU_MUC_DU_LIEU / ten_tep
    return frozenset(dong.strip() for dong in duong_dan.read_text(encoding="utf-8").splitlines() if dong.strip())


def _extract_hot_words(
    name: str, *, tu_dien_anh: frozenset[str], tu_dien_viet: frozenset[str], tu_dien_viet_khong_dau: frozenset[str]
) -> list[str]:
    """Y NGUYÊN thuật toán của `realestate/hot_words.py::extract_hot_words` tại
    thời điểm viết migration — xem docstring module (không import được)."""
    ket_qua: list[str] = []
    da_them: set[str] = set()
    for token in _TOKEN_RE.findall(name):
        if len(token) < 2:
            continue
        thap = token.lower()
        if thap in tu_dien_anh:
            giu = True
        elif thap in tu_dien_viet or _bo_dau(thap) in tu_dien_viet_khong_dau:
            giu = False
        else:
            giu = True
        if not giu:
            continue
        hoa = token.upper()
        if hoa not in da_them:
            da_them.add(hoa)
            ket_qua.append(hoa)
    return ket_qua


def upgrade() -> None:
    tu_dien_anh = _doc_tu_dien("en_words.txt")
    tu_dien_viet = _doc_tu_dien("vi_words.txt")
    tu_dien_viet_khong_dau = frozenset(_bo_dau(tu) for tu in tu_dien_viet)

    conn = op.get_bind()

    op.execute("ALTER TABLE tenant_data.projects NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_data.project_hot_words NO FORCE ROW LEVEL SECURITY")

    hang = (
        conn.execute(
            sa.text("SELECT id, tenant_id, name FROM tenant_data.projects WHERE project_code <> :sentinel"),
            {"sentinel": _SENTINEL_TENANT},
        )
        .mappings()
        .all()
    )

    for r in hang:
        tu = _extract_hot_words(
            r["name"],
            tu_dien_anh=tu_dien_anh,
            tu_dien_viet=tu_dien_viet,
            tu_dien_viet_khong_dau=tu_dien_viet_khong_dau,
        )
        for w in tu:
            conn.execute(
                sa.text(
                    """INSERT INTO tenant_data.project_hot_words (tenant_id, project_id, hot_word)
                            VALUES (:t, :p, :w)
                       ON CONFLICT (tenant_id, hot_word) DO NOTHING"""
                ),
                {"t": r["tenant_id"], "p": r["id"], "w": w},
            )

    op.execute("ALTER TABLE tenant_data.project_hot_words FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_data.projects FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Cố ý KHÔNG xoá dữ liệu đã backfill.

    Không đối xứng với `upgrade()` — nếu hạ xuống dưới `0963` thì chính
    `0963.downgrade()` (`DROP TABLE tenant_data.project_hot_words`) đã dọn sạch
    toàn bộ, kể cả phần do migration này ghi. Không có gì để hoàn tác riêng ở
    đây, và cũng không nên: đây là bản ghi MỘT LẦN backfill, không phải một
    trạng thái schema có thể lật qua lật lại.
    """
