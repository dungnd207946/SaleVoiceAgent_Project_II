"""API cảnh báo mâu thuẫn. Gắn vào ROUTER của kb (xem `kb/router.py`)."""

from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.kb.conflicts import repo
from portal.modules.kb.conflicts.contracts import (
    ConflictCheckOut,
    ConflictOut,
    ConflictSummaryOut,
    ScanAllOut,
    ScanProjectOut,
    conflict_out,
)
from portal.modules.kb.conflicts.enqueue import queue_check

ROUTER = APIRouter()


def _khong_thay() -> loi.LoiPortal:
    return loi.LoiPortal("CONFLICT_NOT_FOUND", 404, "Không tìm thấy cảnh báo mâu thuẫn đang mở")


@ROUTER.get("/conflicts/summary", response_model=list[ConflictSummaryOut])
async def conflict_summary(
    p: Principal = require(ACTIONS.CATALOG_READ), pool: asyncpg.Pool = Depends(lay_pool)
) -> list[ConflictSummaryOut]:
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.summary(conn)
    return [
        ConflictSummaryOut(
            projectCode=r["project_code"],
            name=r["name"],
            open=r["open"],
            checking=r["checking"],
            failed=r["failed"],
            checkedAt=r["checked_at"],
        )
        for r in rows
    ]


@ROUTER.get("/projects/{project_code}/conflicts", response_model=list[ConflictOut])
async def project_conflicts(
    project_code: str, p: Principal = require(ACTIONS.CATALOG_READ), pool: asyncpg.Pool = Depends(lay_pool)
) -> list[ConflictOut]:
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await repo.list_open(conn, project_code)
    return [conflict_out(r) for r in rows]


@ROUTER.get("/projects/{project_code}/conflicts/check", response_model=ConflictCheckOut)
async def check_conflicts(
    project_code: str,
    since: datetime = Query(...),
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> ConflictCheckOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        checking, failed, checked_at = await repo.check_status(conn, project_code)
        rows = await repo.list_open(conn, project_code, since)
    return ConflictCheckOut(
        checking=checking, failed=failed, checkedAt=checked_at, conflicts=[conflict_out(r) for r in rows]
    )


@ROUTER.post("/projects/{project_code}/conflicts/scan", status_code=202, response_model=ScanProjectOut)
async def scan_project(
    project_code: str, p: Principal = require(ACTIONS.CATALOG_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> ScanProjectOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        job_id = await queue_check(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=project_code)
        await nhat_ky.ghi(conn, p.tenant_id, "conflict.scan", p.user_id, {"project_code": project_code})
    return ScanProjectOut(jobId=job_id)


@ROUTER.post("/conflicts/scan", status_code=202, response_model=ScanAllOut)
async def scan_all(p: Principal = require(ACTIONS.CATALOG_WRITE), pool: asyncpg.Pool = Depends(lay_pool)) -> ScanAllOut:
    async with tenant_conn(pool, p.tenant_id) as conn:
        codes = await conn.fetch(
            "SELECT project_code FROM tenant_data.projects"
            " WHERE tenant_id = portal.current_tenant() AND project_code <> $1 ORDER BY project_code",
            repo.SYSTEM_PROJECT,
        )
        queued = 0
        for r in codes:
            queued += (
                await queue_check(conn, tenant_id=p.tenant_id, actor=p.user_id, project_code=r["project_code"])
                is not None
            )
        await nhat_ky.ghi(conn, p.tenant_id, "conflict.scan", p.user_id, {"pham_vi": "tat_ca", "so_du_an": len(codes)})
    return ScanAllOut(queued=queued)


@ROUTER.post("/conflicts/{conflict_id}/dismiss", status_code=204)
async def dismiss_conflict(
    conflict_id: int, p: Principal = require(ACTIONS.CATALOG_WRITE), pool: asyncpg.Pool = Depends(lay_pool)
) -> None:
    async with tenant_conn(pool, p.tenant_id) as conn:
        row = await repo.dismiss(conn, conflict_id, p.user_id)
        if row is None:
            raise _khong_thay()
        await nhat_ky.ghi(
            conn, p.tenant_id, "conflict.dismiss", p.user_id, {"id": conflict_id, "project_code": row["project_code"]}
        )
