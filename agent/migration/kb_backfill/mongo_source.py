"""pymongo reads of the nbx_* mirror (read-only source for the KB backfill)."""
from __future__ import annotations


def connect(uri: str, dbname: str):
    from pymongo import MongoClient  # lazy: keep transform tests import-light
    return MongoClient(uri)[dbname]


def read_all_projects(db) -> list[dict]:
    return list(db.nbx_projects.find({}))


def read_projects(db) -> list[dict]:
    return [d for d in db.nbx_projects.find({}) if (d.get("projectCode") or "").strip()]


def read_units(db, project_oid: str) -> list[dict]:
    return list(db.nbx_units.find({"projectId": project_oid}))
