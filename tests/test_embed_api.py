"""API embed :8013 — một endpoint `/embed`, chiều đi bằng field `side` BẮT BUỘC.

`side` không có default: prefix e5 bất đối xứng nên "quên gửi chiều" phải là 422, không được
là passage âm thầm.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from embed.server import build_app


class FakeDense:
    dim = 4
    last_is_query = None

    def encode(self, texts, *, is_query):
        FakeDense.last_is_query = is_query
        return [[0.5] * self.dim for _ in texts]


class FakeSparse:
    def encode_sparse(self, texts):
        return [{"indices": [1, 7], "values": [0.3, 0.9]} for _ in texts]


class FakeVisualImage:
    dim = 768

    def encode_images(self, images):
        return [[0.1] * self.dim for _ in images]


LOADERS = {
    "dense": FakeDense,
    "sparse": FakeSparse,
    "visual_text": FakeDense,
    "visual_image": FakeVisualImage,
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(token="", loaders=LOADERS))


def png_b64() -> str:
    return base64.b64encode(b"\x89PNG").decode()


def test_side_index_la_passage(client):
    assert client.post("/embed", json={"side": "index", "texts": ["xin chào"]}).status_code == 200
    assert FakeDense.last_is_query is False


def test_side_query_la_query(client):
    assert client.post("/embed", json={"side": "query", "texts": ["xin chào"]}).status_code == 200
    assert FakeDense.last_is_query is True


def test_thieu_side_thi_422(client):
    """Không có default → không thể quên mà nhận sai chiều."""
    r = client.post("/embed", json={"texts": ["x"]})
    assert r.status_code == 422


def test_side_la_thi_400(client):
    r = client.post("/embed", json={"side": "quer", "texts": ["x"]})
    assert r.status_code == 400
    assert "index" in r.json()["detail"] and "query" in r.json()["detail"]


def test_kind_mac_dinh_dense(client):
    body = client.post("/embed", json={"side": "index", "texts": ["x"]}).json()
    assert body["dim"] == 4
    assert body["count"] == 1


def test_response_shape(client):
    body = client.post("/embed", json={"side": "index", "texts": ["x"]}).json()
    assert set(body) == {"embeddings", "dim", "model", "count"}


@pytest.mark.parametrize("field", ["is_query", "normalize"])
def test_field_cu_bi_tu_choi(client, field):
    """Client cũ gửi is_query/normalize → phải 422, không được im lặng bỏ qua."""
    r = client.post("/embed", json={"side": "index", "texts": ["x"], field: True})
    assert r.status_code == 422
    assert field in str(r.json()["detail"])


def test_sparse_dung_duoc_ca_hai_chieu(client):
    """BM25 không có prefix bất đối xứng → cùng vector ở cả hai chiều."""
    a = client.post("/embed", json={"side": "index", "kind": "sparse", "texts": ["x"]}).json()
    b = client.post("/embed", json={"side": "query", "kind": "sparse", "texts": ["x"]}).json()
    assert a["sparse"] == b["sparse"] == [{"indices": [1, 7], "values": [0.3, 0.9]}]
    assert set(a) == {"sparse", "model", "count"}


def test_visual_image_o_side_index(client):
    r = client.post("/embed", json={"side": "index", "kind": "visual_image", "images": [png_b64()]})
    assert r.status_code == 200
    assert len(r.json()["embeddings"][0]) == 768


def test_visual_image_o_side_query_thi_400(client):
    """Ảnh chỉ đi vào index; gọi ở chiều query là dùng sai, nói ra ngay."""
    r = client.post("/embed", json={"side": "query", "kind": "visual_image", "images": [png_b64()]})
    assert r.status_code == 400
    assert "index" in r.json()["detail"]


def test_visual_text_o_side_query(client):
    r = client.post("/embed", json={"side": "query", "kind": "visual_text", "texts": ["hồ bơi"]})
    assert r.status_code == 200
    assert len(r.json()["embeddings"][0]) == 4


def test_visual_text_o_side_index_thi_400(client):
    r = client.post("/embed", json={"side": "index", "kind": "visual_text", "texts": ["x"]})
    assert r.status_code == 400
    assert "query" in r.json()["detail"]


def test_kind_la_thi_400_kem_danh_sach(client):
    r = client.post("/embed", json={"side": "index", "texts": ["x"], "kind": "dracula"})
    assert r.status_code == 400
    assert "dense" in r.json()["detail"]


def test_texts_rong_thi_400(client):
    assert client.post("/embed", json={"side": "index", "texts": []}).status_code == 400


def test_visual_image_thieu_images_thi_400(client):
    r = client.post("/embed", json={"side": "index", "kind": "visual_image"})
    assert r.status_code == 400


def test_khong_con_endpoint_embed_query(client):
    """Đã gộp — đường cũ phải biến mất hẳn, không để hai đường làm một việc."""
    assert client.post("/embed/query", json={"texts": ["x"]}).status_code == 404


def test_health_phoi_cau_hinh(client):
    body = client.get("/health").json()
    assert body["status"] in ("ok", "warming")
    assert "device" in body
    assert "models" in body


def test_auth_cuong_che():
    secured = TestClient(build_app(token="s3cret", loaders=LOADERS))
    assert secured.post("/embed", json={"side": "index", "texts": ["x"]}).status_code == 401
    assert secured.get("/health").status_code == 200
    ok = secured.post(
        "/embed", json={"side": "index", "texts": ["x"]}, headers={"Authorization": "Bearer s3cret"}
    )
    assert ok.status_code == 200


def test_hai_kind_visual_chung_class_chi_nap_mot_lan():
    """Cache theo class: SigLIP2 phục vụ cả hai kind visual, nạp hai lần là tốn gấp đôi RAM."""

    class Visual(FakeDense, FakeVisualImage):
        inits = 0

        def __init__(self):
            Visual.inits += 1

    c = TestClient(build_app(loaders={"visual_text": Visual, "visual_image": Visual}))
    assert c.post("/embed", json={"side": "query", "kind": "visual_text", "texts": ["x"]}).status_code == 200
    r = c.post("/embed", json={"side": "index", "kind": "visual_image", "images": [png_b64()]})
    assert r.status_code == 200
    assert Visual.inits == 1
    assert c.get("/health").json()["loaded"] == ["visual_text", "visual_image"]
