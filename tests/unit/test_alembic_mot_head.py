"""Đồ thị migration phải có ĐÚNG một head.

Ngày 2026-08-06 develop có hai head trong vài giờ: hai MR mở song song cùng nhận
`0911_tenant_id_gach_ngang` làm cha rồi merge riêng rẽ. `make migrate` và `make up`
gãy cho mọi người clone mới và cho CI:

    FAILED: Multiple head revisions are present for given argument 'head'

Git không thấy gì — hai tên tệp khác nhau, không dòng nào đè lên dòng nào, merge
sạch cả hai lần. Chỉ alembic thấy, và chỉ khi ai đó CHẠY migrate. Không cổng nào
chạy `alembic heads`, nên nó đi thẳng vào develop.

Test này là cổng đó. Nó rẻ (đọc tệp, không cần Docker, không cần DB) và nó đỏ
NGAY trong MR thứ hai — đúng lúc còn dễ sửa, thay vì lúc người thứ ba clone về.

Dùng `ScriptDirectory` của chính alembic chứ không tự parse `down_revision`: một
bản tự parse sẽ khác CLI ở đúng những ca hiếm (mergepoint nhiều cha, `depends_on`,
`branch_labels`) — mà mergepoint chính là thứ ta vừa thêm.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

GOC = Path(__file__).resolve().parents[2]


def _thu_muc_script() -> ScriptDirectory:
    cfg = Config(str(GOC / "alembic.ini"))
    cfg.set_main_option("script_location", str(GOC / "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_dung_mot_head():
    heads = _thu_muc_script().get_heads()
    assert len(heads) == 1, (
        f"{len(heads)} head: {sorted(heads)}. Hai MR cùng nhận một cha rồi merge riêng rẽ "
        "⇒ `alembic upgrade head` gãy cho mọi người. Sửa bằng migration hợp nhất "
        "(`down_revision` là tuple hai head), KHÔNG bằng cách đổi `down_revision` của "
        "một nhánh — đổi cha làm alembic coi tổ tiên mới là đã áp trên DB thật ra chưa áp."
    )


def test_moi_revision_deu_toi_duoc_head():
    """Không revision nào mồ côi.

    Một head duy nhất chưa đủ: một revision viết sai `down_revision` (trỏ vào id
    không tồn tại, hoặc tạo một cụm rời) vẫn có thể để lại đúng một head trong khi
    bản thân nó không bao giờ được áp. `walk_revisions` đi từ head xuống base, nên
    revision nào không nằm trong đường đi đó là không tới được.
    """
    import re

    toi_duoc = {r.revision for r in _thu_muc_script().walk_revisions("base", "heads")}
    khai_bao = set()
    for tep in (GOC / "migrations" / "versions").glob("*.py"):
        m = re.search(r'^revision = "([^"]+)"', tep.read_text(), re.M)
        if m:
            khai_bao.add(m.group(1))

    assert khai_bao, "không đọc được revision nào — test này sẽ mù, sửa đường dẫn"
    mo_coi = khai_bao - toi_duoc
    assert not mo_coi, f"revision không tới được từ head (mồ côi): {sorted(mo_coi)}"
