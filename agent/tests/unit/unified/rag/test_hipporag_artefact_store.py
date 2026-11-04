"""Khoá object, tên tệp cache, các nhánh degrade. boto3 là client giả — không mạng."""

from __future__ import annotations

import os

import pytest

from noble_agent.agent.rag.hipporag import artefact_store
from noble_agent.config import settings


class S3Gia:
    def __init__(self, co: set[str] | None = None) -> None:
        self.co = co if co is not None else set()
        self.da_tai: list[tuple[str, str]] = []

    def download_file(self, bucket: str, key: str, path: str) -> None:
        self.da_tai.append((bucket, key))
        if key not in self.co:
            raise FileNotFoundError(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"{}")


@pytest.fixture
def cau_hinh(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "hipporag_artefact_endpoint", "http://minio.test:9000")
    monkeypatch.setattr(settings, "hipporag_artefact_bucket", "portal")
    monkeypatch.setattr(settings, "hipporag_artefact_access_key", "ak")
    monkeypatch.setattr(settings, "hipporag_artefact_secret_key", "sk")
    monkeypatch.setattr(settings, "hipporag_cache_dir", str(tmp_path))


def test_khoa_dung_tien_to_tenant_cua_portal():
    assert artefact_store.khoa("anphu", artefact_store.GRAPH_OBJECT) == "tenants/anphu/hipporag/graph.json"
    assert artefact_store.khoa("anphu", artefact_store.TRIPLE_OBJECT) == "tenants/anphu/hipporag/triple_emb.npz"


def test_npz_cache_dung_ten_ma_triple_index_suy_ra(cau_hinh):
    """Đặt tên khác là sidecar không bao giờ được tìm thấy, sparse seed tắt im lặng."""
    from noble_agent.agent.rag.hipporag.triple_index import triple_emb_path

    graph_path, npz_path = artefact_store.duong_dan_cache("anphu")
    assert npz_path == triple_emb_path(graph_path)


def test_cache_tach_theo_tenant(cau_hinh):
    a, _ = artefact_store.duong_dan_cache("t1")
    b, _ = artefact_store.duong_dan_cache("t2")
    assert a != b and "t1" in a and "t2" in b


def test_chua_cau_hinh_thi_none(monkeypatch):
    monkeypatch.setattr(settings, "hipporag_artefact_endpoint", "")
    monkeypatch.setattr(settings, "hipporag_artefact_bucket", "")
    assert artefact_store.tai_ve("anphu") is None


def test_khong_co_graph_thi_none(cau_hinh, monkeypatch):
    monkeypatch.setattr(artefact_store, "_client", lambda: S3Gia(co=set()))
    assert artefact_store.tai_ve("anphu") is None


def test_co_graph_khong_co_npz_van_tra_graph(cau_hinh, monkeypatch):
    """Graph có, sidecar chưa — PPR vẫn chạy với seed passage; sparse seed tắt."""
    monkeypatch.setattr(artefact_store, "_client", lambda: S3Gia(co={"tenants/anphu/hipporag/graph.json"}))
    p = artefact_store.tai_ve("anphu")
    assert p is not None and os.path.isfile(p)


def test_tai_ca_hai_khi_co_du(cau_hinh, monkeypatch):
    s3 = S3Gia(co={"tenants/anphu/hipporag/graph.json", "tenants/anphu/hipporag/triple_emb.npz"})
    monkeypatch.setattr(artefact_store, "_client", lambda: s3)
    graph_path = artefact_store.tai_ve("anphu")
    _g, npz_path = artefact_store.duong_dan_cache("anphu")
    assert graph_path is not None and os.path.isfile(npz_path)
    assert [k for _b, k in s3.da_tai] == [
        "tenants/anphu/hipporag/graph.json",
        "tenants/anphu/hipporag/triple_emb.npz",
    ]


def test_tenant_rong_thi_lay_current_tenant(cau_hinh, monkeypatch):
    from noble_agent.tenant.current import use_tenant

    s3 = S3Gia(co={"tenants/tx/hipporag/graph.json"})
    monkeypatch.setattr(artefact_store, "_client", lambda: s3)
    with use_tenant("tx"):
        assert artefact_store.tai_ve() is not None
    assert s3.da_tai[0][1] == "tenants/tx/hipporag/graph.json"


def test_loi_s3_bat_ky_thi_none_khong_nem(cau_hinh, monkeypatch):
    class S3Nem:
        def download_file(self, *a, **kw):
            raise RuntimeError("mạng chết")

    monkeypatch.setattr(artefact_store, "_client", lambda: S3Nem())
    assert artefact_store.tai_ve("anphu") is None


def test_mac_dinh_cua_bon_bien_artefact_la_rong():
    """`_env_file=None` để đo mặc định TRONG CODE, không đo `.env` của máy người viết."""
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)
    assert s.hipporag_artefact_endpoint == ""
    assert s.hipporag_artefact_bucket == ""
    assert s.hipporag_artefact_access_key == ""
    assert s.hipporag_artefact_secret_key == ""
