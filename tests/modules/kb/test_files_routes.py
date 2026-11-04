"""Luồng A («Tài liệu tra cứu») + /kb/status + /kb/reindex + phát tệp công khai. Qua HTTP thật."""

import asyncpg
import httpx
import pytest

from portal.core import storage
from portal.core.jobs import run_once
from portal.modules.kb import settings
from portal.modules.kb.contracts import MD_EMPTY_MESSAGE
from tests.modules.kb.conftest import Fakes, seed_product

API = "/api/v1"
MD = "# Hướng dẫn sử dụng\n\n## Sạc pin\n\nDùng cáp USB-C, công suất tối đa 20 W.\n\n## Chống nước\n\nĐạt IP68.\n"


async def _upload(client: httpx.AsyncClient, ten: str, noi_dung: bytes, **form) -> httpx.Response:
    return await client.post(f"{API}/kb/files", files={"file": (ten, noi_dung, "text/markdown")}, data=form)


async def _chay_job_tep(pool: asyncpg.Pool) -> None:
    assert await run_once(pool, kinds=["kb_file_index"]) is not None


async def test_upload_nap_xem_xoa(client: httpx.AsyncClient, admin_pool: asyncpg.Pool, fakes: Fakes) -> None:
    pid = await seed_product(admin_pool)
    r = await _upload(client, "HDSD iPhone.md", MD.encode(), productId=str(pid))
    assert r.status_code == 202, r.text
    tep = r.json()
    assert tep["state"] == "processing" and tep["productId"] == pid and tep["fileType"] == "md"
    assert tep["s3Key"].startswith(settings.FILES_PREFIX) and tep["s3Key"] in fakes.objects.data

    await _chay_job_tep(admin_pool)
    tep = (await client.get(f"{API}/kb/files/{tep['id']}")).json()
    assert tep["state"] == "ready" and tep["chunkCount"] >= 1, tep

    pts = fakes.store.payloads(settings.collection_documents(), doc_type="kb_file", record_id=tep["id"])
    assert len(pts) == tep["chunkCount"]
    assert pts[0]["file_id"] == tep["id"] and pts[0]["file_name"] == "HDSD iPhone.md"
    assert pts[0]["product_id"] == pid and pts[0]["brand"] == "iPhone (Apple)"

    doan = (await client.get(f"{API}/kb/files/{tep['id']}/content")).json()
    assert doan and "USB-C" in "\n".join(d["text"] for d in doan)
    assert not doan[0]["text"].startswith("HDSD iPhone.md")  # tiền tố đã bóc

    ds = (await client.get(f"{API}/kb/files", params={"productId": pid, "state": "ready"})).json()
    assert ds["total"] == 1 and ds["items"][0]["id"] == tep["id"]
    assert (await client.get(f"{API}/kb/files", params={"state": "error"})).json()["total"] == 0

    assert (await client.delete(f"{API}/kb/files/{tep['id']}")).status_code == 204
    assert (await client.get(f"{API}/kb/files/{tep['id']}")).status_code == 404
    assert not fakes.store.payloads(settings.collection_documents(), doc_type="kb_file")
    assert tep["s3Key"] not in fakes.objects.data
    assert (await client.delete(f"{API}/kb/files/{tep['id']}")).status_code == 404


async def test_xoa_van_xong_khi_don_ngoai_hong(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    tep = (await _upload(client, "a.md", MD.encode())).json()

    async def hong(**_kw) -> None:
        raise RuntimeError("qdrant sập")

    monkeypatch.setattr(fakes.store, "delete_by_record", hong)
    assert (await client.delete(f"{API}/kb/files/{tep['id']}")).status_code == 204
    assert await admin_pool.fetchval("SELECT count(*) FROM shop.kb_files") == 0
    assert tep["s3Key"] not in fakes.objects.data


async def test_tep_khong_co_chu_thanh_loi_va_nap_lai(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, fakes: Fakes
) -> None:
    tep = (await _upload(client, "rong.md", b"   \n\n")).json()
    await _chay_job_tep(admin_pool)
    tep = (await client.get(f"{API}/kb/files/{tep['id']}")).json()
    assert tep["state"] == "error" and tep["errorMessage"] == MD_EMPTY_MESSAGE

    r = await client.post(f"{API}/kb/files/{tep['id']}/reindex")
    assert r.status_code == 202 and r.json()["state"] == "processing" and r.json()["errorMessage"] is None
    assert (
        await admin_pool.fetchval("SELECT count(*) FROM shop.jobs WHERE kind = 'kb_file_index' AND state = 'queued'")
        == 1
    )


async def test_loi_ha_tang_khong_de_hang_treo(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    tep = (await _upload(client, "a.md", MD.encode())).json()

    async def hong(texts):
        raise RuntimeError("embed sập")

    monkeypatch.setattr(fakes.embed, "dense", hong)
    await _chay_job_tep(admin_pool)
    tep = (await client.get(f"{API}/kb/files/{tep['id']}")).json()
    assert tep["state"] == "error" and tep["errorMessage"]


@pytest.mark.parametrize(
    ("ten", "noi_dung", "form", "ma"),
    [
        ("anh.png", b"x", {}, 422),
        ("rong.md", b"", {}, 422),
        ("a.md", b"# A", {"productId": "999"}, 422),
        ("a.md", b"# A", {"brandId": "999"}, 422),
    ],
)
async def test_tu_choi_upload(
    client: httpx.AsyncClient, fakes: Fakes, ten: str, noi_dung: bytes, form: dict, ma: int
) -> None:
    r = await _upload(client, ten, noi_dung, **form)
    assert r.status_code == ma, r.text
    assert not fakes.objects.data


async def test_upload_trung_va_qua_dung_luong(
    client: httpx.AsyncClient, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await _upload(client, "a.md", b"# A")).status_code == 202
    r = await _upload(client, "a.md", b"# A")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_FILE"

    monkeypatch.setenv("KB_FILE_MAX_MB", "1")
    r = await _upload(client, "to.md", b"#" * (1024 * 1024 + 1))
    assert r.status_code == 422 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_status_va_reindex(client: httpx.AsyncClient, admin_pool: asyncpg.Pool, fakes: Fakes) -> None:
    await seed_product(admin_pool)
    await _upload(client, "a.md", MD.encode())
    await admin_pool.execute(
        "INSERT INTO shop.kb_index_state (entity, record_id, target, state) VALUES ('faq', 7, 'documents', 'error')"
    )

    r = await client.post(f"{API}/kb/reindex", params={"force": "true"})
    assert r.status_code == 202 and r.json()["jobId"] is not None
    assert (await client.post(f"{API}/kb/reindex", params={"force": "true"})).json()["jobId"] is None

    st = (await client.get(f"{API}/kb/status")).json()
    assert {"entity": "faq", "state": "error", "count": 1} in st["records"]
    assert {"state": "processing", "count": 1} in st["files"]
    viec = {(j["kind"], j["state"]): j["count"] for j in st["jobs"]}
    assert viec[("kb_reindex_all", "queued")] == 1
    assert viec[("kb_file_index", "queued")] == 1
    assert viec[("kb_index", "queued")] >= 1


class _KhoGia:
    async def doc(self, key: str) -> bytes:
        if key == "kb/anh/abc.png":
            return b"\x89PNG"
        raise storage.KhongTimThay(key)


async def test_phat_tep_cong_khai_chi_mo_thu_muc_khai(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "kho_tep_dung_chung", lambda: _KhoGia())
    r = await client.get(f"{API}/public/files/kb/anh/abc.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == b"\x89PNG"
    assert (await client.get(f"{API}/public/files/kb/anh/khong-co.png")).status_code == 404
    for khoa in ("kb/files/sha/hdsd.pdf", "kb/anh/../files/x.pdf", "khac/x.png"):
        assert (await client.get(f"{API}/public/files/{khoa}")).status_code == 404, khoa
