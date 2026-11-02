"""Route `/kb-web/*` của màn «Dữ liệu ngoài» — mỏng, mọi nghiệp vụ ở `service.py`.

Được `modules/kb/router.py` include (`api/app.py::ROUTERS` chỉ gắn `modules/<ten>/router.py`). Quyền: đọc `KB_WEB_READ`,
mọi thay đổi/chạy `KB_WEB_WRITE`. Hợp đồng FE: `docs/contracts/kb-web.md`.
"""

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from redis.asyncio import Redis

from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, lay_redis, require
from portal.modules.kb.web import service
from portal.modules.kb.web.schemas import (
    BaiIn,
    ChiTietDuAnOut,
    ChuDeOut,
    DuAnOut,
    JobOut,
    LamMoiIn,
    LichTongIn,
    LichTongOut,
    MucIn,
    NguonOut,
    OverviewOut,
    SoanChuDeIn,
    SoanChuDeOut,
    SuaChuDeIn,
    SuaNguonIn,
    ThemChuDeIn,
    ThemNguonIn,
    ThuNguonIn,
    ThuNguonOut,
)

ROUTER = APIRouter(prefix="/kb-web", tags=["kb-web"])


class ThuDangChayOut(BaseModel):
    token: str
    jobId: int


class KetQuaThuOut(BaseModel):
    trangThai: str
    """`dang_chay` · `xong` · `loi`"""
    ketQua: ThuNguonOut | None = None


class WorkerOut(BaseModel):
    dangChay: bool


# ─── tổng quan ───────────────────────────────────────────────────────────────


@ROUTER.get("/overview", response_model=OverviewOut)
async def overview(
    p: Principal = require(ACTIONS.KB_WEB_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
    redis: Redis = Depends(lay_redis),
) -> OverviewOut:
    return await service.overview(pool, redis, p.tenant_id)


@ROUTER.get("/worker", response_model=WorkerOut)
async def worker(p: Principal = require(ACTIONS.KB_WEB_READ), redis: Redis = Depends(lay_redis)) -> WorkerOut:
    return WorkerOut(dangChay=await service.worker_alive(redis))


# ─── nguồn ───────────────────────────────────────────────────────────────────


@ROUTER.get("/sources", response_model=list[NguonOut])
async def sources(p: Principal = require(ACTIONS.KB_WEB_READ), pool: asyncpg.Pool = Depends(lay_pool)):
    return await service.list_sources(pool, p.tenant_id)


@ROUTER.post("/sources/probe", response_model=ThuDangChayOut, status_code=202)
async def probe(
    body: ThuNguonIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> ThuDangChayOut:
    token, job_id = await service.start_probe(pool, p.tenant_id, p.user_id, body.url)
    return ThuDangChayOut(token=token, jobId=job_id)


@ROUTER.get("/sources/probe/{token}", response_model=KetQuaThuOut)
async def probe_result(
    token: str,
    p: Principal = require(ACTIONS.KB_WEB_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
    redis: Redis = Depends(lay_redis),
) -> KetQuaThuOut:
    state, result = await service.probe_result(pool, redis, p.tenant_id, token)
    return KetQuaThuOut(trangThai=state, ketQua=result)


@ROUTER.post("/sources", response_model=NguonOut, status_code=201)
async def add_source(
    body: ThemNguonIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> NguonOut:
    return await service.add_source(pool, p.tenant_id, p.user_id, body)


@ROUTER.patch("/sources/{source_id}", response_model=NguonOut)
async def update_source(
    source_id: int,
    body: SuaNguonIn,
    p: Principal = require(ACTIONS.KB_WEB_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> NguonOut:
    return await service.update_source(pool, p.tenant_id, p.user_id, source_id, body)


@ROUTER.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: int, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> None:
    await service.delete_source(pool, p.tenant_id, p.user_id, source_id)


@ROUTER.post("/sources/{source_id}/retry", response_model=ThuDangChayOut, status_code=202)
async def retry_source(
    source_id: int, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> ThuDangChayOut:
    token, job_id = await service.retry_source(pool, p.tenant_id, p.user_id, source_id)
    return ThuDangChayOut(token=token, jobId=job_id)


@ROUTER.post("/sources/{source_id}/probe-result", response_model=NguonOut)
async def apply_probe(
    source_id: int,
    body: ThuNguonOut,
    p: Principal = require(ACTIONS.KB_WEB_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> NguonOut:
    return await service.apply_probe_to_source(pool, p.tenant_id, source_id, body)


# ─── chủ đề ──────────────────────────────────────────────────────────────────


@ROUTER.get("/topics", response_model=list[ChuDeOut])
async def topics(p: Principal = require(ACTIONS.KB_WEB_READ), pool: asyncpg.Pool = Depends(lay_pool)):
    return await service.list_topics(pool, p.tenant_id)


@ROUTER.post("/topics/draft", response_model=SoanChuDeOut)
async def draft_topic(
    body: SoanChuDeIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> SoanChuDeOut:
    return await service.draft_topic(pool, p.tenant_id, body.ten, body.moTa)


@ROUTER.post("/topics", response_model=ChuDeOut, status_code=201)
async def add_topic(
    body: ThemChuDeIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> ChuDeOut:
    return await service.add_topic(pool, p.tenant_id, p.user_id, body)


@ROUTER.patch("/topics/{topic_id}", response_model=ChuDeOut)
async def update_topic(
    topic_id: int,
    body: SuaChuDeIn,
    p: Principal = require(ACTIONS.KB_WEB_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ChuDeOut:
    return await service.update_topic(pool, p.tenant_id, p.user_id, topic_id, body)


@ROUTER.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: int, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> None:
    await service.delete_topic(pool, p.tenant_id, p.user_id, topic_id)


# ─── lịch ────────────────────────────────────────────────────────────────────


@ROUTER.get("/schedules", response_model=LichTongOut)
async def schedules(p: Principal = require(ACTIONS.KB_WEB_READ), pool: asyncpg.Pool = Depends(lay_pool)) -> LichTongOut:
    return await service.get_schedules(pool, p.tenant_id)


@ROUTER.put("/schedules", response_model=LichTongOut)
async def put_schedules(
    body: LichTongIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> LichTongOut:
    return await service.put_schedules(pool, p.tenant_id, p.user_id, body)


@ROUTER.post("/schedules/{mode}/run", response_model=JobOut, status_code=202)
async def run_now(mode: str, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)):
    return await service.run_now(pool, p.tenant_id, p.user_id, mode)


# ─── dự án ───────────────────────────────────────────────────────────────────


@ROUTER.get("/projects", response_model=list[DuAnOut])
async def projects(p: Principal = require(ACTIONS.KB_WEB_READ), pool: asyncpg.Pool = Depends(lay_pool)):
    return await service.list_projects(pool, p.tenant_id)


@ROUTER.get("/projects/{code}", response_model=ChiTietDuAnOut)
async def project_detail(
    code: str, p: Principal = require(ACTIONS.KB_WEB_READ), pool: asyncpg.Pool = Depends(lay_pool)
) -> ChiTietDuAnOut:
    return await service.project_detail(pool, p.tenant_id, code)


@ROUTER.post("/projects/{code}/refresh", response_model=JobOut, status_code=202)
async def refresh_project(
    code: str, body: LamMoiIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> JobOut:
    return await service.refresh_project(pool, p.tenant_id, p.user_id, code, body.mode)


@ROUTER.post("/projects/{code}/items", status_code=204)
async def set_item(
    code: str, body: MucIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> None:
    await service.set_item_hidden(pool, p.tenant_id, p.user_id, code, body.nhan, body.an)


@ROUTER.post("/projects/{code}/pages", status_code=204)
async def set_page(
    code: str, body: BaiIn, p: Principal = require(ACTIONS.KB_WEB_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> None:
    await service.set_page_excluded(pool, p.tenant_id, p.user_id, code, body.url, body.loai)


# ─── nhật ký chạy ────────────────────────────────────────────────────────────


@ROUTER.get("/jobs", response_model=list[JobOut])
async def jobs(
    limit: int = Query(50, ge=1, le=500),
    ngay: int = Query(7, ge=1, le=90),
    p: Principal = require(ACTIONS.KB_WEB_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
):
    return await service.list_jobs(pool, p.tenant_id, limit, days=ngay, show_cost=ACTIONS.BILLING_READ in p.actions)


@ROUTER.get("/jobs/{job_id}", response_model=JobOut)
async def job(job_id: int, p: Principal = require(ACTIONS.KB_WEB_READ), pool: asyncpg.Pool = Depends(lay_pool)):
    return await service.get_job(pool, p.tenant_id, job_id, show_cost=ACTIONS.BILLING_READ in p.actions)
