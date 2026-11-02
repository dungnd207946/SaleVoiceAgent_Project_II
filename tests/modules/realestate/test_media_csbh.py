"""`csbh` KHÔNG còn là danh mục ảnh (migration `0927`).

Bản trước của file này canh chiều ngược: `csbh` vừa được THÊM vào danh mục ảnh (`0918`) vì DB
dev đã nhận nó do sửa tay. Việc đó đúng lúc đó nhưng chỉ là nửa đường — thiết kế vốn đã quyết
chuyển csbh/pháp lý từ ảnh sang tài liệu, và làm nửa đường để lại 34 ảnh csbh KHÔNG CÓ ĐƯỜNG
NÀO tới agent (không point ảnh, không OCR, không nằm trong `documents`) cùng một badge vàng
vĩnh viễn mà bấm nạp bao nhiêu lần cũng không đổi.

`0927` làm xong nửa còn lại: di trú 34 hàng sang `documents` rồi siết CHECK về 7 danh mục.
File này nay canh để không ai thêm nó lại.
"""

import httpx
import pytest


async def test_tao_media_csbh_bi_TU_CHOI_o_bien_HTTP(client_re: httpx.AsyncClient):
    """Chặn ở biên HTTP, không để CHECK của DB gánh: 422 nói rõ giá trị nào hợp lệ, còn
    CheckViolation thành 500 và người dùng không biết mình sai gì."""
    r = await client_re.post(
        "/api/v1/projects/kbs1/media",
        json={"contentType": "image", "category": "csbh", "mediaUrl": "https://x/cs.webp"},
    )
    assert r.status_code == 422, r.text


@pytest.fixture
async def du_an_re(nap_du_an):
    """Một dự án để treo ảnh/tài liệu — cả hai đều có FK tới `projects`."""
    return (await nap_du_an(1))[0]


async def test_bay_danh_muc_anh_con_lai_van_nhan_duoc(client_re: httpx.AsyncClient, du_an_re):
    """Phép đo phải phân biệt "bỏ csbh" với "chặn mọi danh mục" — nếu không thì test trên xanh
    cả khi ai đó làm hỏng toàn bộ đường tạo ảnh."""
    r = await client_re.post(
        f"/api/v1/projects/{du_an_re}/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/a.webp"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["category"] == "tong_quan"


async def test_csbh_van_la_mot_loai_TAI_LIEU(client_re: httpx.AsyncClient, du_an_re):
    """Nó không biến mất khỏi hệ thống — chỉ chuyển chỗ. Loại tài liệu suy từ tiền tố tiêu đề."""
    r = await client_re.post(
        f"/api/v1/projects/{du_an_re}/documents",
        json={"title": "Bảng giá đợt 3", "loai": "csbh", "body": "nội dung"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["loai"] == "csbh"
