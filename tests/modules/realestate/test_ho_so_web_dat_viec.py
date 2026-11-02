"""Dự án vừa thành `published` qua portal thì xếp đúng một việc dựng hồ sơ web (`kbweb_project`, init);
rời `published`, đổi tên hay bị xoá thì xếp việc dọn hồ sơ của tên cũ (`kbweb_purge`)."""

import json

import pytest

pytestmark = pytest.mark.integration

KIND = "kbweb_project"
PURGE = "kbweb_purge"

DU_TRUONG = {
    "name": "Vinhomes Ocean Park 2",
    "region": "Hà Nội",
    "overview": "Đại đô thị biển hồ phía đông.",
    "investor": "Vinhomes",
}


async def _web_jobs(pool, tenant, kind=KIND):
    rows = await pool.fetch(
        "SELECT payload, actor FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, kind
    )
    return [(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"], r["actor"]) for r in rows]


async def test_tao_du_an_published_xep_mot_viec_init(client_re, workspace_re, pool):
    r = await client_re.post("/api/v1/projects", json={"projectCode": "WEB1", **DU_TRUONG, "status": "published"})
    assert r.status_code == 201, r.text
    assert await _web_jobs(pool, workspace_re) == [({"project_code": "WEB1", "mode": "init"}, "u_re")]


async def test_tao_du_an_nhap_khong_xep_viec(client_re, workspace_re, pool):
    r = await client_re.post("/api/v1/projects", json={"projectCode": "WEB2", **DU_TRUONG})
    assert r.status_code == 201, r.text
    assert await _web_jobs(pool, workspace_re) == []


async def test_doi_nhap_sang_published_xep_viec(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB3", **DU_TRUONG})
    r = await client_re.patch("/api/v1/projects/WEB3", json={"status": "published"})
    assert r.status_code == 200, r.text
    assert await _web_jobs(pool, workspace_re) == [({"project_code": "WEB3", "mode": "init"}, "u_re")]


async def test_sua_truong_khac_khi_da_published_khong_xep_them(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB4", **DU_TRUONG, "status": "published"})
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", workspace_re, KIND)
    r = await client_re.patch("/api/v1/projects/WEB4", json={"overview": "Nội dung mới", "status": "published"})
    assert r.status_code == 200, r.text
    assert await _web_jobs(pool, workspace_re) == []


async def test_go_published_xep_viec_don_ho_so(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB5", **DU_TRUONG, "status": "published"})
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", workspace_re, KIND)
    r = await client_re.patch("/api/v1/projects/WEB5", json={"status": "draft"})
    assert r.status_code == 200, r.text
    assert await _web_jobs(pool, workspace_re) == []
    assert await _web_jobs(pool, workspace_re, PURGE) == [({"project_name": DU_TRUONG["name"]}, "u_re")]


async def test_doi_ten_khi_published_don_ten_cu_va_dung_lai(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB8", **DU_TRUONG, "status": "published"})
    await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", workspace_re, KIND)
    r = await client_re.patch("/api/v1/projects/WEB8", json={"name": "Ocean Park Hai"})
    assert r.status_code == 200, r.text
    assert await _web_jobs(pool, workspace_re, PURGE) == [({"project_name": DU_TRUONG["name"]}, "u_re")]
    assert await _web_jobs(pool, workspace_re) == [({"project_code": "WEB8", "mode": "init"}, "u_re")]


async def test_xoa_du_an_xep_viec_don_ho_so(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB9", **DU_TRUONG, "status": "published"})
    r = await client_re.delete("/api/v1/projects/WEB9")
    assert r.status_code == 204, r.text
    assert await _web_jobs(pool, workspace_re, PURGE) == [({"project_name": DU_TRUONG["name"]}, "u_re")]


async def test_bat_tat_lien_tiep_khi_viec_con_cho_chi_mot_viec(client_re, workspace_re, pool):
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB6", **DU_TRUONG, "status": "published"})
    await client_re.patch("/api/v1/projects/WEB6", json={"status": "draft"})
    await client_re.patch("/api/v1/projects/WEB6", json={"status": "published"})
    assert len(await _web_jobs(pool, workspace_re)) == 1


async def test_publish_bi_chan_thi_khong_xep_viec(client_re, workspace_re, pool):
    """Thiếu trường bắt buộc ⇒ 422, giao dịch không ghi gì, kể cả việc."""
    await client_re.post("/api/v1/projects", json={"projectCode": "WEB7", "name": "Nháp"})
    r = await client_re.patch("/api/v1/projects/WEB7", json={"status": "published"})
    assert r.status_code == 422, r.text
    assert await _web_jobs(pool, workspace_re) == []
