"""Tách "hot word" (từ không phải tiếng Việt) từ tên dự án.

Ví dụ: "THE MAGNOLIA - KHAI SƠN" -> ["THE", "MAGNOLIA"] ("KHAI"/"SƠN" là tiếng
Việt, bị loại). Dùng để lưu vào `tenant_data.project_hot_words` (migration
`0963_project_hot_words`) phục vụ tìm kiếm/gợi ý theo từ khoá thương hiệu.

Bốn quy tắc ưu tiên, chốt qua thảo luận với người dùng — thứ tự KHÔNG được đổi:

  1. Token có trong từ điển tiếng Anh (`data/en_words.txt`) -> GIỮ.
     Kiểm TRƯỚC TIÊN vì một số từ tiếng Việt không dấu trùng nguyên văn với từ
     điển tiếng Anh (vd "bay", "sun" đều là từ tiếng Việt hợp lệ KHÔNG dấu,
     đồng thời cũng là từ tiếng Anh) — nếu tra tiếng Việt trước, "Hạ Long Bay"
     sẽ bị loại nhầm "BAY", trái với quyết định của người dùng (thà giữ nhầm
     còn hơn loại nhầm một hot word tiếng Anh thật).
  2. Token khớp NGUYÊN VĂN (kể cả dấu) một mục trong từ điển tiếng Việt
     (`data/vi_words.txt`) -> LOẠI. An toàn tuyệt đối cho token có dấu (vd
     "SƠN") vì từ điển tiếng Anh ở đây chỉ gồm ASCII thuần, không thể trùng.
  3. Token không khớp (1)/(2), nhưng dạng BỎ DẤU của nó trùng dạng bỏ dấu của
     một mục từ điển tiếng Việt -> LOẠI. Bắt các từ tiếng Việt gõ thiếu dấu
     (vd "SON" thay vì "SƠN", "HUNG" thay vì "HƯNG").
  4. Còn lại (không khớp từ điển nào) -> GIỮ. Đây là từ nước ngoài khác (Pháp,
     v.v.) hoặc thương hiệu tự đặt — mặc định giữ khi không xác định được,
     theo đúng lựa chọn của người dùng.

Token dài 1 ký tự bị bỏ qua trước khi vào bốn quy tắc trên — thường là tàn dư
của mã phân khu ("S2", "T1" mất số còn "S"/"T"), không phải hot word có nghĩa.
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_THU_MUC_DU_LIEU = Path(__file__).parent / "data"

_BANG_D = str.maketrans("đĐ", "dD")
"""`đ`/`Đ` không bị NFD tách dấu như các nguyên âm khác — phải tự thay tay."""


def _bo_dau(text: str) -> str:
    text = text.translate(_BANG_D)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text)


def _doc_tu_dien(ten_tep: str) -> frozenset[str]:
    duong_dan = _THU_MUC_DU_LIEU / ten_tep
    return frozenset(dong.strip() for dong in duong_dan.read_text(encoding="utf-8").splitlines() if dong.strip())


@lru_cache(maxsize=1)
def _tu_dien_tieng_viet() -> frozenset[str]:
    return _doc_tu_dien("vi_words.txt")


@lru_cache(maxsize=1)
def _tu_dien_tieng_viet_khong_dau() -> frozenset[str]:
    return frozenset(_bo_dau(tu) for tu in _tu_dien_tieng_viet())


@lru_cache(maxsize=1)
def _tu_dien_tieng_anh() -> frozenset[str]:
    return _doc_tu_dien("en_words.txt")


_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def extract_hot_words(name: str) -> list[str]:
    """Trả về hot word dạng CHỮ HOA, không trùng lặp, giữ đúng thứ tự xuất hiện."""
    tu_dien_anh = _tu_dien_tieng_anh()
    tu_dien_viet = _tu_dien_tieng_viet()
    tu_dien_viet_khong_dau = _tu_dien_tieng_viet_khong_dau()

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
