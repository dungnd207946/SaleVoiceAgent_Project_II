"""Hai endpoint mô tả nháp — 202 rồi poll, đúng luật bất đồng bộ."""

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def test_tao_tra_202_va_job_id(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    r = await client_re.post(
        _url("/media/draft-caption"),
        json={"mediaUrl": "tenants/x/kb-bds/abc/a.jpg", "contentType": "image"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["jobId"]
    hang = await pool.fetchrow("SELECT kind, payload, tenant_id FROM control.jobs WHERE id = $1", job_id)
    assert hang["kind"] == "kb_caption_preview"
    assert hang["tenant_id"] == workspace_re


async def test_thieu_media_url_tra_422(client_re: httpx.AsyncClient):
    r = await client_re.post(_url("/media/draft-caption"), json={"mediaUrl": "  "})
    assert r.status_code == 422


async def test_doc_khi_chua_chay_xong_thi_caption_rong(client_re: httpx.AsyncClient):
    tao = await client_re.post(_url("/media/draft-caption"), json={"mediaUrl": "tenants/x/kb-bds/a/b.jpg"})
    r = await client_re.get(_url(f"/media/draft-caption/{tao.json()['jobId']}"))
    assert r.status_code == 200
    assert r.json()["state"] == "queued"
    assert r.json()["caption"] == ""


async def test_doc_tra_caption_khi_success(client_re: httpx.AsyncClient, pool: asyncpg.Pool):
    tao = await client_re.post(_url("/media/draft-caption"), json={"mediaUrl": "tenants/x/kb-bds/a/b.jpg"})
    job_id = tao.json()["jobId"]
    await pool.execute("UPDATE control.jobs SET state='success', message=$2 WHERE id=$1", job_id, "Toà nhà ven sông.")
    r = await client_re.get(_url(f"/media/draft-caption/{job_id}"))
    assert r.json() == {"state": "success", "caption": "Toà nhà ven sông."}


async def test_job_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.get(_url("/media/draft-caption/99999999"))
    assert r.status_code == 404
