"""Hình dạng API cảnh báo mâu thuẫn (spec §6)."""

from datetime import datetime

import asyncpg
from pydantic import BaseModel


class ConflictSideOut(BaseModel):
    entity: str | None
    recordId: int | None
    field: str | None
    label: str
    quote: str


class ConflictOut(BaseModel):
    id: int
    summary: str
    createdAt: datetime
    left: ConflictSideOut
    right: ConflictSideOut


class ConflictSummaryOut(BaseModel):
    projectCode: str
    name: str
    open: int
    checking: bool
    failed: bool
    checkedAt: datetime | None


class ConflictCheckOut(BaseModel):
    checking: bool
    failed: bool
    checkedAt: datetime | None
    conflicts: list[ConflictOut]


class ScanProjectOut(BaseModel):
    jobId: int | None


class ScanAllOut(BaseModel):
    queued: int


def _side(r: asyncpg.Record, prefix: str) -> ConflictSideOut:
    return ConflictSideOut(
        entity=r[f"{prefix}_entity"],
        recordId=r[f"{prefix}_record_id"],
        field=r[f"{prefix}_field"],
        label=r[f"{prefix}_label"] or "",
        quote=r[f"{prefix}_quote"] or "",
    )


def conflict_out(r: asyncpg.Record) -> ConflictOut:
    return ConflictOut(
        id=r["id"], summary=r["summary"], createdAt=r["created_at"], left=_side(r, "left"), right=_side(r, "right")
    )
