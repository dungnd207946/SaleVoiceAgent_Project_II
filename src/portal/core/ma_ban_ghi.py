"""Sinh `project_code` / `zone_code` — HAI hình dạng, một vòng chống trùng.

VÌ SAO Ở `core/`: HAI module cần cùng luật — `ingest` và `realestate` — và Luật 3
(`tests/test_module_boundaries.py`) cấm module này import ruột module kia. Cùng
tiền lệ đã ghi trong docstring `core/ten_tai_nguyen.py`.

VÌ SAO HAI HÌNH DẠNG chứ không một:
  · `candidate_code` — VIẾT TẮT, cho đường nhập tay. Nguồn là tên thương mại,
    tức văn xuôi: "Vinhomes Ocean Park 2" → `VOP2`. Đo trên 95 tên thật của
    Aurora dev, viết tắt chỉ đụng 10 so với 8 của slug (chênh lệch đến từ tên
    TRÙNG KHÍT, thứ không luật nào cứu) mà rút độ dài trung bình 20.4 → 3.5.
  · `slug_code` — GIỮ TRỌN TỪNG TỪ, cho đường nạp ngoài. Nguồn là `external_id`
    của CRM, thường là UUID; viết tắt một UUID ra chuỗi vô nghĩa và mất luôn
    đường đối chiếu với hệ bên khách.

VÌ SAO SUY TỪ NGUỒN CHỨ KHÔNG NGẪU NHIÊN: mã hiện trên giao diện, đi vào SQL của
agent và vào tên chunk trên Qdrant. Một chuỗi ngẫu nhiên ở đó làm mọi lần đối
chiếu thành một phép tra bảng.

Mã là BẤT BIẾN sau khi tạo (`ProjectPatch` không có ô đó, `0400` không có
`ON UPDATE CASCADE`), nên đổi luật ở đây KHÔNG đổi hàng nào đã lưu.
"""

import re
import unicodedata

import asyncpg

__all__ = [
    "DAI_MA_TOI_DA",
    "can_derive_code",
    "candidate_code",
    "next_project_code",
    "next_zone_code",
    "slug_code",
]

_KHONG_HOP_LE = re.compile(r"[^A-Z0-9]+")
DAI_MA_TOI_DA = 40

_DU_PHONG_SLUG = "DU_AN"
_DU_PHONG_TAT = "DA"
_LAN_TOI_DA = 100


def _tu(source: str) -> list[str]:
    """Nguồn → danh sách từ đã hoa, bỏ dấu, chỉ còn `A-Z0-9`.

    ⚠️ `đ`/`Đ` phải thay TAY: NFD không phân rã nó (nó là một chữ cái riêng,
    không phải `d` cộng dấu), nên chỉ dựa vào NFD thì "Đông" ra `ONG`.
    """
    thay_d = source.replace("đ", "d").replace("Đ", "D")
    khong_dau = "".join(c for c in unicodedata.normalize("NFD", thay_d) if unicodedata.category(c) != "Mn")
    return [w for w in _KHONG_HOP_LE.split(khong_dau.upper()) if w]


def candidate_code(name: str) -> str:
    """Tên thương mại → mã viết tắt. `"Vinhomes Ocean Park 2"` → `"VOP2"`.

    Nhóm toàn số GIỮ NGUYÊN, không rút về một chữ: số là thứ phân biệt hai giai
    đoạn của cùng một dự án (`VOP` với `VOP2`).

    KHÔNG có sàn độ dài — tên hai từ ra mã hai chữ (`Akari City` → `AC`) và thế
    là đủ; đụng thì đã có hậu tố ở `next_*`.
    """
    tat = "".join(w if w.isdigit() else w[0] for w in _tu(name))
    return (tat or _DU_PHONG_TAT)[:DAI_MA_TOI_DA]


def can_derive_code(source: str) -> bool:
    """Nguồn có sinh ra được mã CÓ NGHĨA không.

    Cần một phép kiểm riêng vì `candidate_code` luôn trả một chuỗi: nó có mã dự
    phòng, và `"DA"` là giá trị hợp lệ cho «Đông Anh» đúng như cho `"!!!"` — nên
    so kết quả với mã dự phòng thì loại oan một tên thật.

    Đường nhập tay dùng nó để trả 422 thay vì đúc một mã vô nghĩa mà người dùng
    phải mang vĩnh viễn (mã là bất biến).
    """
    return bool(_tu(source))


def slug_code(source: str) -> str:
    """`"ERP-PRJ-14"` → `"ERP_PRJ_14"`. Giữ trọn từng từ, nối bằng `_`."""
    return ("_".join(_tu(source)) or _DU_PHONG_SLUG)[:DAI_MA_TOI_DA]


def _ma_ke_tiep(goc: str, lan: int) -> str:
    return f"{goc[: DAI_MA_TOI_DA - 4]}_{lan}"


async def next_project_code(conn: asyncpg.Connection, candidate: str) -> str:
    """`candidate` + hậu tố nếu đụng. `project_code` UNIQUE theo `(tenant_id, ...)`.

    Nhận mã ĐÃ SINH chứ không nhận nguồn: vòng chống trùng không cần biết mã tới
    từ hình dạng nào, và để nó biết là để nó có hai nhánh sẽ lệch nhau.
    """
    ma = candidate
    for lan in range(2, _LAN_TOI_DA):
        co = await conn.fetchval(
            "SELECT 1 FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = $1",
            ma,
        )
        if co is None:
            return ma
        ma = _ma_ke_tiep(candidate, lan)
    raise RuntimeError(f"không sinh được project_code duy nhất từ {candidate!r}")


async def next_zone_code(conn: asyncpg.Connection, project_code: str, candidate: str) -> str:
    """`zone_code` — UNIQUE trong phạm vi `(tenant_id, project_code)`, không toàn tenant."""
    ma = candidate
    for lan in range(2, _LAN_TOI_DA):
        co = await conn.fetchval(
            "SELECT 1 FROM tenant_data.zones WHERE tenant_id = portal.current_tenant() "
            "AND project_code = $1 AND zone_code = $2",
            project_code,
            ma,
        )
        if co is None:
            return ma
        ma = _ma_ke_tiep(candidate, lan)
    raise RuntimeError(f"không sinh được zone_code duy nhất từ {candidate!r}")
