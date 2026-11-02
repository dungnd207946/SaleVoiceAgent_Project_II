"""Bearer dùng chung. Token rỗng = mở (dev loopback); có token = cưỡng chế."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from embed.auth import require_token


def make_client(token: str) -> TestClient:
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(require_token(token))])
    def x():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return TestClient(app)


def test_token_rong_thi_cho_qua():
    assert make_client("").get("/x").status_code == 200


def test_token_dung_thi_cho_qua():
    r = make_client("s3cret").get("/x", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_token_sai_thi_401():
    r = make_client("s3cret").get("/x", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_thieu_header_thi_401():
    assert make_client("s3cret").get("/x").status_code == 401


def test_health_khong_bi_chan():
    """CI gate và probe của compose gọi /health không kèm token."""
    assert make_client("s3cret").get("/health").status_code == 200


@pytest.mark.parametrize("header", ["s3cret", "bearer s3cret", "Bearer  s3cret "])
def test_chiu_duoc_bien_the_header(header):
    """Client cũ gửi thiếu prefix hoặc lệch hoa/thường vẫn phải qua — token mới là thứ xác thực."""
    r = make_client("s3cret").get("/x", headers={"Authorization": header})
    assert r.status_code == 200
