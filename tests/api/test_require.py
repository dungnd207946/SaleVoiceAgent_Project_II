"""CỔNG 2 — require() từ chối action lạ NGAY LÚC IMPORT.

Vì sao lúc import chứ không lúc chạy: một endpoint khai `require('project.read')`
(thiếu chữ s) mà chỉ nổ khi có người gọi thì nó im lặng tới production. Nổ lúc
import nghĩa là app không khởi động được — không ai merge được thứ đó.
"""

import httpx
import pytest
from fastapi import FastAPI

from portal.api.loi import dang_ky_handler_loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import require


def test_action_la_bi_tu_choi_luc_import():
    with pytest.raises(ValueError) as e:
        require("khong.ton.tai")
    assert "khong.ton.tai" in str(e.value)


def test_action_go_sai_mot_ky_tu_cung_bi_bat():
    """Trường hợp thật sự hay xảy ra không phải tên bịa, mà là thiếu một chữ s."""
    with pytest.raises(ValueError):
        require("overview.reads")


def test_action_dung_thi_khong_raise():
    require(ACTIONS.WORKSPACE_ADMIN)


def test_route_cong_khai_phai_khai_ly_do():
    """`require(None)` trần không phân biệt được với 'quên khai'. Bắt buộc lý do
    để cổng 1 (§6.1) đọc được ý định, không phải đoán."""
    with pytest.raises(ValueError) as e:
        require(None)
    assert "ly_do" in str(e.value)


def test_route_cong_khai_co_ly_do_thi_duoc():
    require(None, ly_do="đăng nhập — chưa có phiên nên không kiểm được gì")


def test_ca_hai_nhanh_deu_gan_marker_cho_cong_1():
    """Cổng 1 phân biệt "công khai có chủ ý" với "quên khai" bằng marker này. Nếu
    nhánh công khai không gắn marker thì hai trường hợp trông giống hệt nhau, và
    mọi endpoint quên khai đều lọt."""
    co_quyen = require(ACTIONS.OVERVIEW_READ)
    cong_khai = require(None, ly_do="test")

    assert co_quyen.dependency.khai_quyen.action == ACTIONS.OVERVIEW_READ
    assert cong_khai.dependency.khai_quyen.action is None
    assert cong_khai.dependency.khai_quyen.ly_do == "test"


async def test_khong_co_cookie_thi_401_va_khong_cham_db():
    """Không có phiên là 401 NO_SESSION, không phải 403: chưa biết anh là ai thì
    chưa nói được chuyện anh có quyền hay không.

    `pool` và `redis` để None CÓ CHỦ Ý — nếu require() chạm tới chúng trên đường
    này thì test nổ AttributeError chứ không lặng lẽ xanh. Nghĩa là test còn khẳng
    định thêm: request không có cookie bị chối TRƯỚC mọi việc với DB và Redis. Một
    trận flood không cookie không được biến thành một trận flood vào Postgres.

    (Chối được sớm như vậy là nhờ chốt chặn `if not session_id` trong
    core/auth/session.doc — không có nó thì đường này vẫn phải hỏi Redis.)
    """
    app = FastAPI()
    dang_ky_handler_loi(app)
    app.state.pool = None
    app.state.redis = None

    @app.get("/thu")
    async def thu(p: Principal = require(ACTIONS.OVERVIEW_READ)) -> dict[str, str]:
        return {"user": p.user_id}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/thu")

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NO_SESSION"


async def test_route_cong_khai_vao_duoc_khong_can_cookie():
    app = FastAPI()
    dang_ky_handler_loi(app)

    @app.get("/mo")
    async def mo(_: None = require(None, ly_do="test")) -> dict[str, bool]:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/mo")

    assert r.status_code == 200
